"""D1-I1 pure MCP resource admission core.

This module admits one explicitly selected, identity-pinned, read-only remote
MCP resource server over an injected transport.  It performs no I/O, imports no
transport or MCP SDK, exposes no MCP tools, and has no path into supervisor
routing or native tool contexts.

The transport is deliberately narrow.  A future transport may describe one
server and read one already-admitted resource; this core owns admission,
fingerprint re-verification, resource allowlisting, bounds, redaction, and
revocation.  In D1-I1 only test fakes implement the transport.
"""

from dataclasses import dataclass
import hashlib
import ipaddress
import json
import re
from typing import Dict, Iterable, Optional, Protocol, Tuple
from urllib.parse import urlsplit


UNTRUSTED_EXTERNAL = "untrusted-external"
_PROVIDER_BINDING_TOKEN = object()

_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(api[_-]?key|secret|token|password|passwd|authorization)\b"
    r"(\s*[:=]\s*)(\S+)"
)
_PRIVATE_KEY_BLOCK = re.compile(
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
)
class MCPResourceCoreError(Exception):
    """A bounded, fail-closed refusal from the admission core."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ServerSnapshot:
    """Untrusted server description returned by the injected transport."""

    server_identity: str
    capabilities: Tuple[str, ...]
    resources: Tuple[str, ...]


@dataclass(frozen=True)
class ResourcePayload:
    """Untrusted resource body returned by the injected transport."""

    resource_uri: str
    content: str


@dataclass(frozen=True)
class MCPResourceAdmission:
    """Immutable record for the single currently admitted server."""

    admission_id: int
    normalized_identity: str
    normalized_origin: str
    expected_server_identity: str
    reported_server_identity: str
    capabilities: Tuple[str, ...]
    allowed_resource_uris: Tuple[str, ...]
    fingerprint: str


@dataclass(frozen=True, init=False)
class UntrustedExternalResource:
    """Bounded, redacted content structurally barred from action contexts.

    ``provider_bound`` records that redaction has completed before the value
    may enter a future dedicated text-only retrieval context.  It does not
    grant routing or native-tool eligibility; both are permanently false.
    The private construction token prevents callers from forging a
    provider-bound value without passing through the core's redaction path.
    """

    content: str
    original_length: int
    retained_length: int
    truncated: bool
    redaction_count: int
    provenance: str
    provider_bound: bool
    routing_eligible: bool
    native_tool_eligible: bool

    def __init__(
        self,
        content: str,
        original_length: int,
        retained_length: int,
        truncated: bool,
        redaction_count: int,
        *,
        _binding_token: object,
    ):
        if _binding_token is not _PROVIDER_BINDING_TOKEN:
            raise TypeError("UntrustedExternalResource is core-constructed only")
        object.__setattr__(self, "content", content)
        object.__setattr__(self, "original_length", original_length)
        object.__setattr__(self, "retained_length", retained_length)
        object.__setattr__(self, "truncated", truncated)
        object.__setattr__(self, "redaction_count", redaction_count)
        object.__setattr__(self, "provenance", UNTRUSTED_EXTERNAL)
        object.__setattr__(self, "provider_bound", True)
        object.__setattr__(self, "routing_eligible", False)
        object.__setattr__(self, "native_tool_eligible", False)


class MCPResourceTransport(Protocol):
    """Injected, read-only transport boundary used by this core."""

    def describe_server(self, identity: str) -> ServerSnapshot:
        """Return the current untrusted server description."""

    def read_resource(self, identity: str, resource_uri: str) -> ResourcePayload:
        """Return one remote resource body selected by the caller."""


def _refuse(code: str) -> None:
    raise MCPResourceCoreError(code)


def _canonical_https_url(value: str, *, require_origin: Optional[str] = None) -> Tuple[str, str]:
    """Validate and canonicalize one HTTPS URL without resolving or opening it."""

    if not isinstance(value, str) or not value or value.strip() != value:
        _refuse("invalid_url")
    if any(character.isspace() for character in value):
        _refuse("invalid_url")
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        _refuse("invalid_url")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        _refuse("invalid_url")
    if parsed.scheme.lower() != "https":
        _refuse("https_required")
    if not parsed.hostname or parsed.username is not None or parsed.password is not None:
        _refuse("invalid_url")
    if parsed.fragment:
        _refuse("invalid_url")
    if port is not None and not 1 <= port <= 65535:
        _refuse("invalid_url")
    if parsed.netloc.startswith("[") and ":" not in parsed.hostname:
        _refuse("invalid_url")

    if parsed.query:
        _refuse("credential_bearing_url")

    host = parsed.hostname.lower().rstrip(".")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is None:
        try:
            host = host.encode("idna").decode("ascii")
        except UnicodeError:
            _refuse("invalid_url")
        labels = host.split(".")
        if (
            not host
            or any(
                not label
                or len(label) > 63
                or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in labels
            )
        ):
            _refuse("invalid_url")
        if (
            host == "localhost"
            or host.endswith(".localhost")
            or host.endswith(".local")
            or host.endswith(".localdomain")
        ):
            _refuse("non_remote_host")
    elif (
        address.is_loopback
        or address.is_link_local
        or address.is_unspecified
        or address.is_private
        or address.is_reserved
        or address.is_multicast
    ):
        _refuse("non_remote_host")

    default_port = 443 if port is None else port
    authority_host = host if ":" not in host else "[{}]".format(host)
    origin = "https://{}:{}".format(authority_host, default_port)
    if require_origin is not None and origin != require_origin:
        _refuse("origin_mismatch")
    normalized = "{}://{}".format(parsed.scheme.lower(), authority_host)
    if default_port != 443:
        normalized += ":{}".format(default_port)
    normalized += parsed.path or "/"
    return normalized, origin


def _normalized_capabilities(capabilities: Iterable[str]) -> Tuple[str, ...]:
    if isinstance(capabilities, (str, bytes)):
        _refuse("invalid_snapshot")
    try:
        values = tuple(capabilities)
    except TypeError:
        _refuse("invalid_snapshot")
    if any(not isinstance(value, str) or not value for value in values):
        _refuse("invalid_snapshot")
    normalized = tuple(sorted(set(value.strip().lower() for value in values)))
    if any(value == "tools" or value.startswith("tools.") or value.startswith("tools:") for value in normalized):
        _refuse("tools_capability")
    return normalized


def _redact(text: str) -> Tuple[str, int]:
    """Apply deterministic secret-shaped redaction and return replacement count."""

    count = 0

    def _assignment(match):
        nonlocal count
        count += 1
        return "{}{}{}".format(match.group(1), match.group(2), "[REDACTED]")

    def _block(_match):
        nonlocal count
        count += 1
        return "[REDACTED_PRIVATE_KEY]"

    redacted = _SECRET_ASSIGNMENT.sub(_assignment, text)
    redacted = _PRIVATE_KEY_BLOCK.sub(_block, redacted)
    return redacted, count


def _truncate_utf8(text: str, limit: int) -> Tuple[str, bool]:
    """Truncate on a code-point boundary at a deterministic byte limit."""

    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


def _fingerprint(
    normalized_identity: str,
    reported_server_identity: str,
    capabilities: Tuple[str, ...],
    resources: Tuple[str, ...],
) -> str:
    payload = json.dumps(
        {
            "identity": normalized_identity,
            "server_identity": reported_server_identity,
            "capabilities": list(capabilities),
            "resources": list(resources),
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class MCPResourceAdmissionCore:
    """One-server, resources-only admission and retrieval core.

    The core owns no transport implementation.  It asks the injected
    transport for a description and one selected body, but it never lists
    tools, invokes tools, resolves local paths, or performs dynamic code.
    """

    def __init__(
        self,
        transport: MCPResourceTransport,
        *,
        max_admitted_resources: int = 1000,
        max_bytes_per_resource: int = 262144,
        max_total_bytes: int = 1048576,
        max_uri_length: int = 2048,
        max_truncated_bytes: int = 262144,
    ):
        if not callable(getattr(transport, "describe_server", None)):
            raise TypeError("transport must provide describe_server(identity)")
        if not callable(getattr(transport, "read_resource", None)):
            raise TypeError("transport must provide read_resource(identity, resource_uri)")
        limits = {
            "max_admitted_resources": max_admitted_resources,
            "max_bytes_per_resource": max_bytes_per_resource,
            "max_total_bytes": max_total_bytes,
            "max_uri_length": max_uri_length,
            "max_truncated_bytes": max_truncated_bytes,
        }
        for name, value in limits.items():
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError("{} must be a positive integer".format(name))
        self.transport = transport
        self.max_admitted_resources = max_admitted_resources
        self.max_bytes_per_resource = max_bytes_per_resource
        self.max_total_bytes = max_total_bytes
        self.max_uri_length = max_uri_length
        self.max_truncated_bytes = max_truncated_bytes
        self._admission: Optional[MCPResourceAdmission] = None
        self._admission_id = 0
        self._total_bytes = 0
        self._content_cache: Dict[str, UntrustedExternalResource] = {}

    def _clear_admission(self) -> None:
        self._admission = None
        self._total_bytes = 0
        self._content_cache.clear()

    def admit(
        self,
        *,
        identity: str,
        expected_server_identity: str,
        allowed_resource_uris: Iterable[str],
    ) -> MCPResourceAdmission:
        """Explicitly admit one remote server and its exact resource allowlist."""

        normalized_identity, origin = _canonical_https_url(identity)
        if not isinstance(expected_server_identity, str) or not expected_server_identity.strip():
            _refuse("invalid_server_identity")
        if isinstance(allowed_resource_uris, (str, bytes)):
            _refuse("invalid_allowlist")
        try:
            resources = tuple(allowed_resource_uris)
        except TypeError:
            _refuse("invalid_allowlist")
        if not resources:
            _refuse("invalid_allowlist")
        if len(resources) > self.max_admitted_resources:
            _refuse("resource_count_exceeded")
        if any(not isinstance(resource_uri, str) for resource_uri in resources):
            _refuse("invalid_resource_uri")
        if len(set(resources)) != len(resources):
            _refuse("duplicate_resource_uri")

        normalized_resources = []
        for resource_uri in resources:
            if not isinstance(resource_uri, str) or len(resource_uri) > self.max_uri_length:
                _refuse("invalid_resource_uri")
            normalized_resource, _ = _canonical_https_url(
                resource_uri,
                require_origin=origin,
            )
            normalized_resources.append(normalized_resource)
        normalized_resources_tuple = tuple(normalized_resources)
        if len(set(normalized_resources_tuple)) != len(normalized_resources_tuple):
            _refuse("duplicate_resource_uri")

        try:
            snapshot = self.transport.describe_server(normalized_identity)
        except Exception:
            _refuse("transport_failure")
        if not isinstance(snapshot, ServerSnapshot):
            _refuse("invalid_snapshot")
        capabilities = _normalized_capabilities(snapshot.capabilities)
        if not isinstance(snapshot.server_identity, str) or not snapshot.server_identity.strip():
            _refuse("invalid_snapshot")
        if snapshot.server_identity != expected_server_identity:
            _refuse("server_identity_mismatch")
        if isinstance(snapshot.resources, (str, bytes)):
            _refuse("invalid_snapshot")
        try:
            advertised = tuple(snapshot.resources)
        except TypeError:
            _refuse("invalid_snapshot")
        if len(advertised) > self.max_admitted_resources:
            _refuse("resource_count_exceeded")
        if any(not isinstance(resource_uri, str) for resource_uri in advertised):
            _refuse("invalid_resource_uri")
        if len(set(advertised)) != len(advertised):
            _refuse("duplicate_resource_uri")
        normalized_advertised = []
        for resource_uri in advertised:
            if not isinstance(resource_uri, str) or len(resource_uri) > self.max_uri_length:
                _refuse("invalid_resource_uri")
            normalized_resource, _ = _canonical_https_url(
                resource_uri,
                require_origin=origin,
            )
            normalized_advertised.append(normalized_resource)
        normalized_advertised_tuple = tuple(sorted(normalized_advertised))
        if len(set(normalized_advertised_tuple)) != len(normalized_advertised_tuple):
            _refuse("duplicate_resource_uri")
        if not set(normalized_resources_tuple).issubset(set(normalized_advertised_tuple)):
            _refuse("resource_not_advertised")

        fingerprint = _fingerprint(
            normalized_identity,
            snapshot.server_identity,
            capabilities,
            normalized_advertised_tuple,
        )
        self._clear_admission()
        self._admission_id += 1
        self._admission = MCPResourceAdmission(
            admission_id=self._admission_id,
            normalized_identity=normalized_identity,
            normalized_origin=origin,
            expected_server_identity=expected_server_identity,
            reported_server_identity=snapshot.server_identity,
            capabilities=capabilities,
            allowed_resource_uris=normalized_resources_tuple,
            fingerprint=fingerprint,
        )
        return self._admission


    def revoke(self) -> None:
        """Revoke the current admission and invalidate all cached content."""

        self._clear_admission()

    def _current_admission(self, admission: MCPResourceAdmission) -> MCPResourceAdmission:
        if self._admission is None or admission is not self._admission:
            _refuse("not_admitted")
        return self._admission

    def _verify_fingerprint(self, admission: MCPResourceAdmission) -> None:
        try:
            snapshot = self.transport.describe_server(admission.normalized_identity)
        except Exception:
            _refuse("transport_failure")
        if not isinstance(snapshot, ServerSnapshot):
            _refuse("invalid_snapshot")
        capabilities = _normalized_capabilities(snapshot.capabilities)
        if not isinstance(snapshot.server_identity, str) or not snapshot.server_identity.strip():
            _refuse("invalid_snapshot")
        if isinstance(snapshot.resources, (str, bytes)):
            _refuse("invalid_snapshot")
        try:
            advertised = tuple(snapshot.resources)
        except TypeError:
            _refuse("invalid_snapshot")
        normalized_advertised = []
        for resource_uri in advertised:
            if not isinstance(resource_uri, str) or len(resource_uri) > self.max_uri_length:
                _refuse("invalid_resource_uri")
            normalized_resource, _ = _canonical_https_url(
                resource_uri,
                require_origin=admission.normalized_origin,
            )
            normalized_advertised.append(normalized_resource)
        if len(normalized_advertised) > self.max_admitted_resources:
            _refuse("resource_count_exceeded")
        if len(set(normalized_advertised)) != len(normalized_advertised):
            _refuse("duplicate_resource_uri")
        normalized_advertised_tuple = tuple(sorted(normalized_advertised))
        if len(set(normalized_advertised_tuple)) != len(normalized_advertised_tuple):
            _refuse("duplicate_resource_uri")
        current = _fingerprint(
            admission.normalized_identity,
            snapshot.server_identity,
            capabilities,
            tuple(sorted(normalized_advertised)),
        )
        if current != admission.fingerprint:
            _refuse("fingerprint_changed")

    def read_resource(
        self,
        *,
        admission: MCPResourceAdmission,
        resource_uri: str,
    ) -> UntrustedExternalResource:
        """Read one explicitly allowlisted resource after re-verification."""

        self._current_admission(admission)
        if not isinstance(resource_uri, str):
            _refuse("invalid_resource_uri")
        normalized_uri, _ = _canonical_https_url(
            resource_uri,
            require_origin=admission.normalized_origin,
        )
        if normalized_uri not in admission.allowed_resource_uris:
            _refuse("resource_not_allowed")
        self._verify_fingerprint(admission)

        try:
            payload = self.transport.read_resource(
                admission.normalized_identity,
                normalized_uri,
            )
        except Exception:
            _refuse("transport_failure")
        if not isinstance(payload, ResourcePayload):
            _refuse("invalid_resource_payload")
        if payload.resource_uri != normalized_uri:
            _refuse("resource_identity_changed")
        if not isinstance(payload.content, str):
            _refuse("invalid_resource_payload")
        original_length = len(payload.content.encode("utf-8"))
        if original_length > self.max_bytes_per_resource:
            _refuse("resource_bytes_exceeded")
        if self._total_bytes + original_length > self.max_total_bytes:
            _refuse("total_bytes_exceeded")

        redacted, redaction_count = _redact(payload.content)
        retained, truncated = _truncate_utf8(redacted, self.max_truncated_bytes)
        retained_length = len(retained.encode("utf-8"))
        result = UntrustedExternalResource(
            content=retained,
            original_length=original_length,
            retained_length=retained_length,
            truncated=truncated,
            redaction_count=redaction_count,
            _binding_token=_PROVIDER_BINDING_TOKEN,
        )
        self._total_bytes += original_length
        self._content_cache[normalized_uri] = result
        return result
