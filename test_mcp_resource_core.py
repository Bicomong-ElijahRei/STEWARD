"""D1-I1 pure MCP resource admission-core regressions."""

import ast
import builtins
import http.client
import inspect
import socket
import subprocess
import unittest
import urllib.request
from unittest.mock import patch

from agents.mcp_resource_core import (
    MCPResourceCoreError,
    MCPResourceAdmissionCore,
    ResourcePayload,
    ServerSnapshot,
    UNTRUSTED_EXTERNAL,
)


SERVER_URI = "https://example.com/mcp/resource/one"
OTHER_URI = "https://example.com/mcp/resource/two"
THIRD_URI = "https://example.com/mcp/resource/three"
OTHER_SERVER_URI = "https://other.example/mcp/resource/one"
SERVER_IDENTITY = "server-identity-v1"


class FakeTransport:
    """In-memory transport fake; direct execution is intentionally forbidden."""

    def __init__(self, snapshots=None, contents=None):
        self.snapshots = list(snapshots or [ServerSnapshot(
            server_identity=SERVER_IDENTITY,
            capabilities=("resources",),
            resources=(SERVER_URI,),
        )])
        self.contents = dict(contents or {SERVER_URI: "ordinary content"})
        self.describe_calls = []
        self.read_calls = []
        self.execute_calls = 0

    def describe_server(self, identity):
        self.describe_calls.append(identity)
        if len(self.snapshots) == 1:
            return self.snapshots[0]
        return self.snapshots.pop(0)

    def read_resource(self, identity, resource_uri):
        self.read_calls.append((identity, resource_uri))
        if resource_uri not in self.contents:
            raise AssertionError("unexpected resource read")
        return ResourcePayload(resource_uri=resource_uri, content=self.contents[resource_uri])

    def execute(self, *_args, **_kwargs):
        self.execute_calls += 1
        raise AssertionError("MCP content or transport must never be executed directly")


def admit(core, identity="https://example.com/mcp", expected=SERVER_IDENTITY,
          resources=(SERVER_URI,)):
    return core.admit(
        identity=identity,
        expected_server_identity=expected,
        allowed_resource_uris=resources,
    )


class MCPResourceIdentityAdmissionTests(unittest.TestCase):
    def test_refuses_non_https_and_non_network_schemes_before_transport(self):
        identities = (
            "http://example.com/mcp",
            "file:///tmp/mcp",
            "ws://example.com/mcp",
            "wss://example.com/mcp",
            "stdio://example.com/mcp",
            "example.com/mcp",
            "",
        )
        for identity in identities:
            with self.subTest(identity=identity):
                transport = FakeTransport()
                core = MCPResourceAdmissionCore(transport)
                with self.assertRaises(MCPResourceCoreError):
                    admit(core, identity=identity)
                self.assertEqual(transport.describe_calls, [])
                self.assertEqual(transport.read_calls, [])

    def test_refuses_malformed_userinfo_and_credential_query_urls(self):
        identities = (
            "https://",
            "https:///mcp",
            "https://exa mple.com/mcp",
            "https://example.com:bad/mcp",
            "https://example.com:70000/mcp",
            "https://example.com/%zz/mcp",
            "https://user@example.com/mcp",
            "https://user:password@example.com/mcp",
            "https://example.com/mcp?api_key=secret",
            "https://example.com/mcp?access_token=secret",
            "https://example.com/mcp?opaque=value",
            "https://example.com/mcp#fragment",
        )
        for identity in identities:
            with self.subTest(identity=identity):
                transport = FakeTransport()
                core = MCPResourceAdmissionCore(transport)
                with self.assertRaises(MCPResourceCoreError):
                    admit(core, identity=identity)
                self.assertEqual(transport.describe_calls, [])
                self.assertEqual(transport.read_calls, [])

    def test_refuses_loopback_link_local_unspecified_and_private_addresses(self):
        identities = (
            "https://127.0.0.1/mcp",
            "https://127.42.0.9/mcp",
            "https://169.254.169.254/mcp",
            "https://0.0.0.0/mcp",
            "https://[::1]/mcp",
            "https://[::]/mcp",
            "https://[fe80::1]/mcp",
            "https://[fc00::1]/mcp",
            "https://10.0.0.1/mcp",
            "https://172.16.0.1/mcp",
            "https://192.168.0.1/mcp",
            "https://localhost/mcp",
        )
        for identity in identities:
            with self.subTest(identity=identity):
                transport = FakeTransport()
                core = MCPResourceAdmissionCore(transport)
                with self.assertRaises(MCPResourceCoreError) as caught:
                    admit(core, identity=identity)
                self.assertEqual(caught.exception.code, "non_remote_host")
                self.assertEqual(transport.describe_calls, [])
                self.assertEqual(transport.read_calls, [])

    def test_normalizes_canonical_identity_and_requires_exact_server_identity(self):
        transport = FakeTransport()
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core, identity="https://EXAMPLE.com:443")
        self.assertEqual(admission.normalized_identity, "https://example.com/")
        self.assertEqual(admission.reported_server_identity, SERVER_IDENTITY)
        self.assertEqual(transport.describe_calls, ["https://example.com/"])

    def test_public_idna_and_ipv6_hosts_are_canonicalized(self):
        cases = (
            (
                "https://bücher.example/mcp",
                "https://xn--bcher-kva.example/mcp/resource/one",
                "https://xn--bcher-kva.example/mcp",
                "https://xn--bcher-kva.example:443",
            ),
            (
                "https://[2606:4700:4700::1111]/mcp",
                "https://[2606:4700:4700::1111]/mcp/resource/one",
                "https://[2606:4700:4700::1111]/mcp",
                "https://[2606:4700:4700::1111]:443",
            ),
        )
        for identity, resource_uri, expected_identity, expected_origin in cases:
            with self.subTest(identity=identity):
                transport = FakeTransport(snapshots=[ServerSnapshot(
                    SERVER_IDENTITY, ("resources",), (resource_uri,),
                )], contents={resource_uri: "ordinary content"})
                core = MCPResourceAdmissionCore(transport)
                admission = admit(core, identity=identity, resources=(resource_uri,))
                self.assertEqual(admission.normalized_identity, expected_identity)
                self.assertEqual(admission.normalized_origin, expected_origin)
                self.assertEqual(admission.allowed_resource_uris, (resource_uri,))

    def test_non_default_port_remains_pinned_in_identity_and_resource_origin(self):
        identity = "https://example.com:8443/mcp"
        resource_uri = "https://example.com:8443/mcp/resource/one"
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (resource_uri,),
        )], contents={resource_uri: "ordinary content"})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core, identity=identity, resources=(resource_uri,))
        self.assertEqual(admission.normalized_identity, identity)
        self.assertEqual(admission.normalized_origin, "https://example.com:8443")
        self.assertEqual(admission.allowed_resource_uris, (resource_uri,))
        result = core.read_resource(admission=admission, resource_uri=resource_uri)
        self.assertEqual(result.content, "ordinary content")
        self.assertEqual(transport.describe_calls, [identity, identity])
        self.assertEqual(transport.read_calls, [(identity, resource_uri)])

    def test_resource_on_different_port_is_refused_before_transport_read(self):
        identity = "https://example.com:8443/mcp"
        wrong_uri = "https://example.com/mcp/resource/one"
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (wrong_uri,),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core, identity=identity, resources=(wrong_uri,))
        self.assertEqual(caught.exception.code, "origin_mismatch")
        self.assertEqual(transport.read_calls, [])

    def test_rejects_mismatched_server_reported_identity(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            server_identity="different-server",
            capabilities=("resources",),
            resources=(SERVER_URI,),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError):
            admit(core)
        self.assertEqual(transport.read_calls, [])


class MCPResourceCapabilityAndFingerprintTests(unittest.TestCase):
    def test_tools_capability_advertisement_refuses_admission(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            server_identity=SERVER_IDENTITY,
            capabilities=("resources", "tools"),
            resources=(SERVER_URI,),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core)
        self.assertEqual(caught.exception.code, "tools_capability")
        self.assertEqual(transport.read_calls, [])

    def test_tool_capability_name_variants_are_refused(self):
        for capability in ("tools", "Tools", "tools.listChanged", "tools:list"):
            with self.subTest(capability=capability):
                transport = FakeTransport(snapshots=[ServerSnapshot(
                    server_identity=SERVER_IDENTITY,
                    capabilities=("resources", capability),
                    resources=(SERVER_URI,),
                )])
                core = MCPResourceAdmissionCore(transport)
                with self.assertRaises(MCPResourceCoreError):
                    admit(core)

    def test_changed_capability_fingerprint_between_admission_and_use_refuses(self):
        transport = FakeTransport(snapshots=[
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
            ServerSnapshot(SERVER_IDENTITY, ("resources", "logging"), (SERVER_URI,)),
        ])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "fingerprint_changed")
        self.assertEqual(transport.read_calls, [])

    def test_changed_reported_server_identity_refuses_use(self):
        transport = FakeTransport(snapshots=[
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
            ServerSnapshot("server-identity-v2", ("resources",), (SERVER_URI,)),
        ])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "fingerprint_changed")

    def test_changed_resource_declaration_refuses_use(self):
        transport = FakeTransport(snapshots=[
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (OTHER_URI,)),
        ])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "fingerprint_changed")


class MCPResourceAllowlistTests(unittest.TestCase):
    def test_non_allowlisted_resource_refuses_before_read(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (SERVER_URI, OTHER_URI),
        )])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=OTHER_URI)
        self.assertEqual(caught.exception.code, "resource_not_allowed")
        self.assertEqual(transport.read_calls, [])

    def test_new_resource_not_in_allowlist_refuses_before_read(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (SERVER_URI, OTHER_URI),
        )])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core, resources=(SERVER_URI,))
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=OTHER_URI)
        self.assertEqual(caught.exception.code, "resource_not_allowed")
        self.assertEqual(transport.read_calls, [])

    def test_allowlist_must_be_explicit_and_unique(self):
        transport = FakeTransport()
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError):
            admit(core, resources=())
        with self.assertRaises(MCPResourceCoreError):
            admit(core, resources=(SERVER_URI, SERVER_URI))

    def test_enumerated_resources_do_not_implicitly_admit_them(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (SERVER_URI, OTHER_URI),
        )])
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core, resources=(SERVER_URI,))
        self.assertEqual(admission.allowed_resource_uris, (SERVER_URI,))
        with self.assertRaises(MCPResourceCoreError):
            core.read_resource(admission=admission, resource_uri=OTHER_URI)

    def test_canonically_duplicate_allowlist_entries_are_refused(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (SERVER_URI,),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core, resources=(
                "https://example.com/mcp/resource/one",
                "https://EXAMPLE.com:443/mcp/resource/one",
            ))
        self.assertEqual(caught.exception.code, "duplicate_resource_uri")

    def test_canonically_duplicate_advertisements_are_refused(self):
        canonical = "https://example.com/mcp/resource/one"
        equivalent = "https://EXAMPLE.com:443/mcp/resource/one"
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (canonical, equivalent),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core)
        self.assertEqual(caught.exception.code, "duplicate_resource_uri")

    def test_allowlisted_resource_must_be_advertised_at_admission(self):
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (SERVER_URI,),
        )])
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core, resources=(SERVER_URI, OTHER_URI))
        self.assertEqual(caught.exception.code, "resource_not_advertised")
        self.assertEqual(transport.read_calls, [])

    def test_resource_uri_must_be_remote_https_on_the_admitted_origin(self):
        for uri in (
            "http://example.com/mcp/resource/one",
            "file:///tmp/resource",
            "https://other.example/mcp/resource/one",
            "https://user@example.com/mcp/resource/one",
        ):
            with self.subTest(uri=uri):
                transport = FakeTransport(snapshots=[ServerSnapshot(
                    SERVER_IDENTITY, ("resources",), (uri,),
                )], contents={uri: "ok"})
                core = MCPResourceAdmissionCore(transport)
                with self.assertRaises(MCPResourceCoreError):
                    admit(core, resources=(uri,))


class MCPResourceBoundsAndContentTests(unittest.TestCase):
    def test_maximum_resources_passes_at_limit_and_refuses_at_limit_plus_one(self):
        resources = (SERVER_URI, OTHER_URI, THIRD_URI)
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), resources,
        )])
        core = MCPResourceAdmissionCore(transport, max_admitted_resources=3)
        admission = admit(core, resources=resources)
        self.assertEqual(len(admission.allowed_resource_uris), 3)
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), resources,
        )])
        core = MCPResourceAdmissionCore(transport, max_admitted_resources=2)
        with self.assertRaises(MCPResourceCoreError):
            admit(core, resources=resources)

    def test_maximum_bytes_per_resource_passes_at_limit_and_refuses_at_limit_plus_one(self):
        content = "x" * 9
        transport = FakeTransport(contents={SERVER_URI: content})
        core = MCPResourceAdmissionCore(transport, max_bytes_per_resource=9)
        admission = admit(core)
        result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(result.content, content)
        transport = FakeTransport(contents={SERVER_URI: "x" * 10})
        core = MCPResourceAdmissionCore(transport, max_bytes_per_resource=9)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "resource_bytes_exceeded")

    def test_maximum_total_bytes_passes_at_limit_and_refuses_at_limit_plus_one(self):
        resources = (SERVER_URI, OTHER_URI)
        contents = {SERVER_URI: "x" * 5, OTHER_URI: "y" * 5}
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), resources,
        )], contents=contents)
        core = MCPResourceAdmissionCore(transport, max_total_bytes=10)
        admission = admit(core, resources=resources)
        core.read_resource(admission=admission, resource_uri=SERVER_URI)
        core.read_resource(admission=admission, resource_uri=OTHER_URI)
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), resources,
        )], contents=contents)
        core = MCPResourceAdmissionCore(transport, max_total_bytes=9)
        admission = admit(core, resources=resources)
        core.read_resource(admission=admission, resource_uri=SERVER_URI)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=OTHER_URI)
        self.assertEqual(caught.exception.code, "total_bytes_exceeded")

    def test_maximum_uri_length_passes_at_limit_and_refuses_at_limit_plus_one(self):
        base = "https://example.com/"
        at_limit = base + "x" * 20
        over_limit = base + "x" * 21
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (at_limit,),
        )], contents={at_limit: "ok"})
        core = MCPResourceAdmissionCore(transport, max_uri_length=len(at_limit))
        admission = admit(core, resources=(at_limit,))
        self.assertEqual(admission.allowed_resource_uris, (at_limit,))
        transport = FakeTransport(snapshots=[ServerSnapshot(
            SERVER_IDENTITY, ("resources",), (over_limit,),
        )], contents={over_limit: "ok"})
        core = MCPResourceAdmissionCore(transport, max_uri_length=len(at_limit))
        with self.assertRaises(MCPResourceCoreError):
            admit(core, resources=(over_limit,))

    def test_truncation_is_deterministic_and_reports_lengths_and_flag(self):
        transport = FakeTransport(contents={SERVER_URI: "abcdefghij"})
        core = MCPResourceAdmissionCore(transport, max_bytes_per_resource=10,
                                        max_truncated_bytes=4)
        admission = admit(core)
        first = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        second = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(first, second)
        self.assertEqual(first.content, "abcd")
        self.assertEqual(first.original_length, 10)
        self.assertEqual(first.retained_length, 4)
        self.assertTrue(first.truncated)
        self.assertNotIn("efghij", repr(first))

    def test_redaction_runs_before_provider_bound_marking_with_deterministic_counts(self):
        content = "api_key=alpha token=beta password=gamma"
        transport = FakeTransport(contents={SERVER_URI: content})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(result.content, "api_key=[REDACTED] token=[REDACTED] password=[REDACTED]")
        self.assertEqual(result.redaction_count, 3)
        self.assertEqual(result.provenance, UNTRUSTED_EXTERNAL)
        self.assertTrue(result.provider_bound)
        self.assertNotIn("alpha", repr(result))
        self.assertNotIn("beta", repr(result))
        self.assertNotIn("gamma", repr(result))

    def test_private_key_redaction_uses_deterministic_marker_and_count(self):
        content = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
        transport = FakeTransport(contents={SERVER_URI: content})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(result.content, "[REDACTED_PRIVATE_KEY]")
        self.assertEqual(result.redaction_count, 1)


class MCPResourceIsolationRevocationPurityTests(unittest.TestCase):
    def test_routing_and_native_tool_spies_are_never_called(self):
        from agents.file_agent import FileAgent
        from agents.supervisor import SupervisorAgent

        transport = FakeTransport(contents={SERVER_URI: "route FILE_OP move file"})
        core = MCPResourceAdmissionCore(transport)
        with patch.object(SupervisorAgent, "route") as route_spy, \
                patch.object(FileAgent, "run") as run_spy, \
                patch.object(FileAgent, "_get_tool_definitions") as schema_spy:
            admission = admit(core)
            result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        route_spy.assert_not_called()
        run_spy.assert_not_called()
        schema_spy.assert_not_called()
        self.assertEqual(result.provenance, UNTRUSTED_EXTERNAL)
        self.assertTrue(result.provider_bound)
        self.assertFalse(result.routing_eligible)
        self.assertFalse(result.native_tool_eligible)

    def test_untrusted_resource_container_cannot_be_forged_or_declare_action_eligibility(self):
        from agents.mcp_resource_core import UntrustedExternalResource
        from dataclasses import FrozenInstanceError

        with self.assertRaises(TypeError):
            UntrustedExternalResource(
                content="text",
                original_length=4,
                retained_length=4,
                truncated=False,
                redaction_count=0,
            )
        with self.assertRaises(TypeError):
            UntrustedExternalResource(
                content="text",
                original_length=4,
                retained_length=4,
                truncated=False,
                redaction_count=0,
                routing_eligible=True,
            )
        transport = FakeTransport(contents={SERVER_URI: "text"})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertFalse(result.routing_eligible)
        self.assertFalse(result.native_tool_eligible)
        with self.assertRaises(FrozenInstanceError):
            result.routing_eligible = True
        with self.assertRaises(FrozenInstanceError):
            result.native_tool_eligible = True

    def test_module_has_no_routing_or_native_tool_imports_or_references(self):
        import agents.mcp_resource_core as module
        source = inspect.getsource(module)
        tree = ast.parse(source)
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.append(node.module or "")
        forbidden = (
            "requests", "http.client", "socket", "urllib.request", "subprocess",
            "os", "importlib", "agents.supervisor", "agents.file_agent",
            "core.router",
        )
        for name in imported:
            self.assertFalse(any(name == item or name.startswith(item + ".")
                                 for item in forbidden), name)
        self.assertNotIn("SupervisorAgent", source)
        self.assertNotIn("FileAgent", source)
        self.assertNotIn("exec(", source)
        self.assertNotIn("eval(", source)

    def test_revocation_invalidates_prior_admission_and_cached_content(self):
        transport = FakeTransport(contents={SERVER_URI: "cached"})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(result.content, "cached")
        core.revoke()
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "not_admitted")

    def test_readmission_of_same_identity_invalidates_prior_admission(self):
        transport = FakeTransport()
        core = MCPResourceAdmissionCore(transport)
        first = admit(core)
        second = admit(core)
        self.assertIsNot(first, second)
        with self.assertRaises(MCPResourceCoreError):
            core.read_resource(admission=first, resource_uri=SERVER_URI)

    def test_readmission_of_different_identity_invalidates_prior_resources(self):
        transport = FakeTransport(snapshots=[
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (OTHER_SERVER_URI,)),
        ])
        core = MCPResourceAdmissionCore(transport)
        first = admit(core)
        second = admit(core, identity="https://other.example/mcp",
                       resources=(OTHER_SERVER_URI,))
        self.assertIsNot(first, second)
        self.assertEqual(second.normalized_identity, "https://other.example/mcp")
        with self.assertRaises(MCPResourceCoreError):
            core.read_resource(admission=first, resource_uri=SERVER_URI)

    def test_network_subprocess_filesystem_and_dynamic_code_spies_are_never_called(self):
        transport = FakeTransport(contents={SERVER_URI: "eval('not code')"})
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with patch.object(http.client, "HTTPConnection") as http_spy, \
                patch.object(socket, "socket") as socket_spy, \
                patch.object(socket, "create_connection") as create_spy, \
                patch.object(urllib.request, "urlopen") as urlopen_spy, \
                patch.object(subprocess, "Popen") as popen_spy, \
                patch.object(subprocess, "run") as run_spy, \
                patch.object(builtins, "open") as open_spy, \
                patch.object(builtins, "exec") as exec_spy, \
                patch.object(builtins, "eval") as eval_spy:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        http_spy.assert_not_called()
        socket_spy.assert_not_called()
        create_spy.assert_not_called()
        urlopen_spy.assert_not_called()
        popen_spy.assert_not_called()
        run_spy.assert_not_called()
        open_spy.assert_not_called()
        exec_spy.assert_not_called()
        eval_spy.assert_not_called()
        self.assertEqual(transport.execute_calls, 0)

    def test_transport_failures_are_translated_to_bounded_typed_refusals(self):
        class FailingDescribeTransport(FakeTransport):
            def describe_server(self, identity):
                raise RuntimeError("implementation-specific secret detail")

        transport = FailingDescribeTransport()
        core = MCPResourceAdmissionCore(transport)
        with self.assertRaises(MCPResourceCoreError) as caught:
            admit(core)
        self.assertEqual(caught.exception.code, "transport_failure")
        self.assertEqual(str(caught.exception), "transport_failure")

        class FailingReadTransport(FakeTransport):
            def read_resource(self, identity, resource_uri):
                raise RuntimeError("implementation-specific secret detail")

        transport = FailingReadTransport()
        core = MCPResourceAdmissionCore(transport)
        admission = admit(core)
        with self.assertRaises(MCPResourceCoreError) as caught:
            core.read_resource(admission=admission, resource_uri=SERVER_URI)
        self.assertEqual(caught.exception.code, "transport_failure")
        self.assertEqual(str(caught.exception), "transport_failure")

    def test_identical_inputs_and_scripts_are_deterministic(self):
        scripts = [
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
            ServerSnapshot(SERVER_IDENTITY, ("resources",), (SERVER_URI,)),
        ]
        outputs = []
        for _ in range(2):
            transport = FakeTransport(snapshots=list(scripts),
                                     contents={SERVER_URI: "same content"})
            core = MCPResourceAdmissionCore(transport)
            admission = admit(core)
            result = core.read_resource(admission=admission, resource_uri=SERVER_URI)
            outputs.append((admission, result))
        self.assertEqual(outputs[0], outputs[1])
        self.assertEqual(outputs[0][0].fingerprint, outputs[1][0].fingerprint)
        self.assertEqual(outputs[0][1].content, outputs[1][1].content)


if __name__ == "__main__":
    unittest.main()
