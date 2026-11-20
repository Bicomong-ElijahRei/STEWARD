"""Discover free OpenRouter models without modifying existing providers."""

from __future__ import annotations

import logging
import sqlite3
import threading
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Iterable, Mapping, Optional

import requests

from core.database import get_db, init_db


OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 15.0

logger = logging.getLogger(__name__)


class DiscoveryError(RuntimeError):
    """A model-catalog request or response could not be processed."""


@dataclass(frozen=True)
class DiscoveredModel:
    """The provider fields needed to register one discovered model."""

    model_id: str
    display_name: str


@dataclass(frozen=True)
class DiscoveryResult:
    """A non-raising discovery outcome suitable for a GUI callback."""

    discovered: int = 0
    added: int = 0
    skipped: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None


def fetch_openrouter_models(timeout: float = DEFAULT_TIMEOUT) -> list[dict[str, Any]]:
    """Fetch and validate the OpenRouter catalog, raising a descriptive error."""
    try:
        response = requests.get(OPENROUTER_MODELS_URL, timeout=timeout)
    except requests.exceptions.RequestException as exc:
        raise DiscoveryError(f"Could not reach OpenRouter: {exc}") from exc

    if not 200 <= response.status_code < 300:
        raise DiscoveryError(
            f"OpenRouter model discovery returned HTTP {response.status_code}."
        )

    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise DiscoveryError("OpenRouter returned an invalid JSON response.") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise DiscoveryError(
            "OpenRouter returned an unexpected response; missing a 'data' list."
        )

    return [model for model in payload["data"] if isinstance(model, dict)]


def _is_free_price(value: object) -> bool:
    """Accept numeric and string representations of zero, but not booleans."""
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return value == 0
    if isinstance(value, str):
        try:
            return Decimal(value.strip()) == 0
        except (InvalidOperation, ValueError):
            return False
    return False


def filter_free_models(
    models: Iterable[Mapping[str, Any]],
) -> list[DiscoveredModel]:
    """Extract valid, unique models whose prompt token price is zero."""
    free_models: list[DiscoveredModel] = []
    seen_ids: set[str] = set()

    for model in models:
        pricing = model.get("pricing")
        if not isinstance(pricing, Mapping) or not _is_free_price(pricing.get("prompt")):
            continue

        raw_id = model.get("id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            continue
        model_id = raw_id.strip()
        if model_id in seen_ids:
            continue

        raw_name = model.get("name")
        display_name = raw_name.strip() if isinstance(raw_name, str) else ""
        free_models.append(
            DiscoveredModel(model_id=model_id, display_name=display_name or model_id)
        )
        seen_ids.add(model_id)

    return free_models


def upsert_discovered_models(models: Iterable[DiscoveredModel]) -> tuple[int, int]:
    """Insert missing models and leave every existing provider row untouched.

    Names are unique in the providers table. Model IDs also identify existing
    OpenRouter rows when their display name changes. Avoiding add_provider() for
    duplicates is essential because its conflict path replaces API keys.

    Returns:
        A tuple of (number added, number skipped).
    """
    try:
        db = get_db()
    except RuntimeError:
        db = init_db()
    providers = db.get_all_providers()
    existing_names = {
        provider.get("name") for provider in providers if provider.get("name")
    }
    existing_openrouter_ids = {
        provider.get("model_name")
        for provider in providers
        if provider.get("model_name")
        and str(provider.get("base_url") or "").rstrip("/") == OPENROUTER_BASE_URL
    }

    added = 0
    skipped = 0
    for model in models:
        if (
            model.display_name in existing_names
            or model.model_id in existing_openrouter_ids
        ):
            skipped += 1
            continue

        db.add_provider(
            name=model.display_name,
            base_url=OPENROUTER_BASE_URL,
            api_key="",
            model_name=model.model_id,
            is_local=False,
            is_active=False,
        )
        existing_names.add(model.display_name)
        existing_openrouter_ids.add(model.model_id)
        added += 1

    return added, skipped


def discover_free_models(timeout: float = DEFAULT_TIMEOUT) -> DiscoveryResult:
    """Fetch, filter, and register free models without crashing the caller."""
    try:
        models = filter_free_models(fetch_openrouter_models(timeout=timeout))
        added, skipped = upsert_discovered_models(models)
        return DiscoveryResult(
            discovered=len(models), added=added, skipped=skipped
        )
    except Exception as exc:
        message = str(exc)
        logger.warning("OpenRouter model discovery failed: %s", message)
        return DiscoveryResult(error=message)


def start_discovery(
    callback: Optional[Callable[[DiscoveryResult], None]] = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> threading.Thread:
    """Run discovery in a daemon thread and return the started thread.

    The callback executes on the worker thread. Tkinter callers should marshal
    UI updates back to their main thread, for example with ``widget.after``.
    """

    def worker() -> None:
        result = discover_free_models(timeout=timeout)
        if callback is not None:
            try:
                callback(result)
            except Exception:
                logger.exception("OpenRouter discovery callback failed")

    thread = threading.Thread(
        target=worker, name="steward-model-discovery", daemon=True
    )
    thread.start()
    return thread

