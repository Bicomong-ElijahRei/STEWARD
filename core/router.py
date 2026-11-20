"""Intelligent provider routing for STEWARD's OpenAI-compatible APIs."""

import time
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Any, Dict, List, Optional

import requests

from core.database import get_db


class APIManager:
    """Route LLM requests across validated providers with automatic fallback."""

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout

    def route_request(
        self,
        messages: list,
        agent_name: str,
        required_tier: str = None,
        require_tools: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> dict:
        """Route to the fastest eligible provider and return its raw JSON."""
        started = time.perf_counter()
        db = get_db()
        providers = db.get_active_providers()
        now = datetime.now()

        eligible = [
            provider
            for provider in providers
            if not self._is_cooling_down(provider.get("cooldown_until"), now)
            and (required_tier is None or provider.get("intelligence_tier") == required_tier)
            and (not require_tools or bool(provider.get("supports_tools")))
        ]
        eligible.sort(key=self._speed_score)

        cloud_providers = [provider for provider in eligible if not provider.get("is_local")]
        local_providers = sorted(
            (provider for provider in providers if provider.get("is_local")),
            key=self._speed_score,
        )
        candidates = cloud_providers + local_providers[:1]

        provider_chain = []
        last_error = "No active providers match the requested capabilities."

        for provider in candidates:
            name = provider.get("name") or provider.get("base_url") or "Unknown"
            try:
                response = requests.post(
                    self._endpoint(provider["base_url"]),
                    json=self._payload(provider, messages, tools),
                    headers={
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {provider.get('api_key', '')}",
                    },
                    timeout=self.timeout,
                )
            except requests.exceptions.Timeout:
                provider_chain.append(f"{name}: Timeout")
                last_error = f"{name}: request timed out after {self.timeout}s"
                self._register_transient_failure(db, provider)
                continue
            except requests.exceptions.RequestException as exc:
                provider_chain.append(f"{name}: Connection error")
                last_error = f"{name}: {exc}"
                continue

            status_code = response.status_code
            if status_code == 429:
                retry_after = self._retry_after_seconds(response.headers.get("Retry-After"))
                cooldown_until = datetime.now() + timedelta(seconds=retry_after)
                db.update_provider_fields(
                    name=provider["name"], cooldown_until=cooldown_until.isoformat()
                )
                provider_chain.append(f"{name}: 429")
                last_error = self._http_error(name, response)
                continue

            if status_code in (401, 403):
                db.update_provider_fields(name=provider["name"], is_active=0)
                provider_chain.append(f"{name}: {status_code}")
                last_error = self._http_error(name, response)
                continue

            if 500 <= status_code <= 599:
                self._register_transient_failure(db, provider)
                provider_chain.append(f"{name}: {status_code}")
                last_error = self._http_error(name, response)
                continue

            if not 200 <= status_code < 300:
                provider_chain.append(f"{name}: {status_code}")
                last_error = self._http_error(name, response)
                continue

            try:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("response JSON is not an object")
            except ValueError as exc:
                provider_chain.append(f"{name}: Invalid JSON")
                last_error = f"{name}: invalid response JSON ({exc})"
                continue

            usage = data.get("usage") or {}
            tokens_used = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
            db.update_provider_fields(
                name=provider["name"], failure_count=0, cooldown_until=None
            )
            db.record_usage(provider["id"], tokens_used=tokens_used)
            provider_chain.append(f"{name}: Success")
            db.record_trace(
                agent_name=agent_name,
                latency_ms=self._elapsed_ms(started),
                provider_chain=provider_chain,
                status="Success",
            )
            return data

        db.record_trace(
            agent_name=agent_name,
            latency_ms=self._elapsed_ms(started),
            provider_chain=provider_chain,
            status="Failure",
            error_msg=last_error,
        )
        raise RuntimeError(f"All providers failed. Final error: {last_error}")

    @staticmethod
    def _speed_score(provider: dict) -> float:
        score = provider.get("speed_score_ms")
        return float(score) if score is not None else 9999.0

    @staticmethod
    def _is_cooling_down(cooldown_until: Optional[str], now: datetime) -> bool:
        if not cooldown_until:
            return False
        try:
            cooldown = datetime.fromisoformat(str(cooldown_until).replace("Z", "+00:00"))
            if cooldown.tzinfo is not None:
                return cooldown > datetime.now(cooldown.tzinfo)
            return cooldown > now
        except (TypeError, ValueError):
            return False

    @staticmethod
    def _endpoint(base_url: str) -> str:
        return f"{base_url.rstrip('/')}/chat/completions"

    @staticmethod
    def _payload(
        provider: dict, messages: list, tools: Optional[List[Dict[str, Any]]]
    ) -> dict:
        payload = {
            "model": provider.get("model_name") or "default",
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        return payload

    @staticmethod
    def _retry_after_seconds(value: Optional[str]) -> int:
        if not value:
            return 60
        try:
            return max(0, int(float(value)))
        except (TypeError, ValueError):
            try:
                retry_at = parsedate_to_datetime(value)
                now = datetime.now(retry_at.tzinfo) if retry_at.tzinfo else datetime.now()
                return max(0, int((retry_at - now).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                return 60

    @staticmethod
    def _http_error(name: str, response: requests.Response) -> str:
        detail = (response.text or "").strip()[:500]
        suffix = f" - {detail}" if detail else ""
        return f"{name}: HTTP {response.status_code}{suffix}"

    @staticmethod
    def _register_transient_failure(db, provider: dict) -> None:
        failure_count = int(provider.get("failure_count") or 0) + 1
        fields = {"failure_count": failure_count}
        if failure_count > 3:
            fields["cooldown_until"] = (datetime.now() + timedelta(minutes=5)).isoformat()
        db.update_provider_fields(name=provider["name"], **fields)

    @staticmethod
    def _elapsed_ms(started: float) -> int:
        return int((time.perf_counter() - started) * 1000)
