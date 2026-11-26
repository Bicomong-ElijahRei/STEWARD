# STEWARD D1-SURVEY — published MCP server survey and admission decision

**Status:** documentation-only decision; no MCP transport, dependency, configuration, connection, or runtime capability was added

**Survey date:** 2026-11-26

**Decision:** **DEFER D1-I2.** None of the ten examined published servers has evidence establishing all seven D1-I1 admission rules. Keep D1 in BACKLOG and make no product-content choice on the owner's behalf.

## Problem

D1-R selected one explicitly admitted, identity-pinned, read-only remote MCP **resource** server usable from chat. D1-I1 added a fail-closed admission core; D1-DEP selected the official `mcp==2.3.0` SDK for a future D1-I2 implementation. The remaining product decision was whether a published MCP server can satisfy that narrow boundary. This survey asks whether published evidence identifies one candidate before implementation begins.

The question is deliberately narrower than “does an MCP server exist?” and “is a server read-only?” A server that exposes only read-only tools is still tool-capable. The MCP specification requires a server that supports tools to declare the `tools` capability, so read-only intent or behavior does not satisfy the resources-only rule. [S5] [S6]

### Scope and non-goals

This survey:

- queries only the official MCP Registry API and its published `server.json` records;
- reads published protocol material, the SEP-2127 server-card specification and schema, and vendor documentation;
- evaluates the published Registry/server-card/vendor evidence against all seven D1-I1 admission rules;
- records PASS, FAIL, or UNKNOWN for every rule and candidate, with the exact missing evidence for any UNKNOWN; and
- recommends PROCEED or DEFER while leaving D1 in BACKLOG.

This survey does not:

- connect to, initialize, probe, or list resources from any candidate MCP endpoint;
- infer runtime capabilities from a title, description, “read-only” wording, or a successful-looking URL;
- install the SDK, add a dependency, alter code, configure a server, or change runtime behavior; or
- decide what content the project should read.

### The seven binding rules

The rules below restate the D1-I1 admission boundary in [`agents/mcp_resource_core.py`](../agents/mcp_resource_core.py). [S1]

1. **HTTPS transport:** the admitted remote identity is HTTPS, not plaintext HTTP, WebSocket, stdio, or a local transport.
2. **Public remote host:** the host is not a literal loopback, private, reserved, link-local, multicast, or unspecified address, and is not `localhost` or a local-domain suffix. The implementation performs this check syntactically; it does not resolve DNS or prove live reachability. [S1]
3. **Clean URL:** the identity has no whitespace, malformed percent escape, userinfo, fragment, invalid port, or query string. D1-I1 conservatively rejects every query-bearing URL because a query cannot be proven credential-free. [S1]
4. **Resources, not tools:** the published capability evidence must establish that the server advertises `resources` and does **not** advertise `tools`. The implementation directly refuses `tools`, `tools.*`, and `tools:*`; it does not synthesize a positive `resources` declaration, so rule 4's positive half requires evidence. [S1]
5. **Enumerated, same-origin resources:** the server's resource URI set must be enumerable from published evidence, and every allowed URI must use the identity's effective HTTPS origin. A nonempty allowlist must be a subset of the advertised set. [S1]
6. **Stable advertised resource set:** the D1-I1 SHA-256 snapshot fingerprint covers normalized identity, reported server identity, normalized capabilities, and the order-independent advertised resource set, and must not change between reads. [S1]
7. **Credentials out of URLs:** authentication, if any, is carried outside the URL. The URL must not carry userinfo, query credentials, fragments, or other credential material. [S1]

PASS means the cited published evidence establishes the rule. FAIL means the cited evidence establishes non-compliance. UNKNOWN means the published evidence is insufficient; UNKNOWN is never treated as compatibility.

## Design

### Published-evidence model

The official Registry list endpoint is a paginated, name-searchable catalog. Its `version=latest` filter returns one latest record per matching server; following `metadata.nextCursor` preserves filters. A version record contains installation and connection metadata such as identity, packages, remotes, headers, repository, and website, but the standard `server.json` schema has no runtime capability or advertised-resource field. The Registry's publisher-provided `_meta` extension is intentionally open-ended, not a standardized capability preview. [S2] [S3]

SEP-2127 server cards do not close that gap. A card is pre-connection metadata for identity, transports, and protocol versions. Its schema explicitly excludes primitive definitions: tools, resources, and prompts remain subject to runtime list operations. Card fields are advisory and must be reconciled with live behavior, so a card cannot substitute for rule 4 capability evidence, rule 5 resource enumeration, or rule 6 fingerprint stability. [S4]

The normative MCP tools specification resolves one important ambiguity: “Servers that support tools **MUST** declare the `tools` capability.” Therefore a vendor's published list of tools is affirmative evidence of rule-4 failure, even when the tools are described as read-only. [S5]

### Candidate selection

The official Registry was searched by server name for `resource`, `library`, `knowledge`, `documentation`, and `reference`, using `version=latest`. The retained set contains published Registry entries whose descriptions plausibly indicate retrieval/reference content, plus prominent documentation/reference servers and a read-only comparison case. The official AWS documentation server was retained as a vendor-published comparison even though the official Registry search returned no matching latest identity. [S2] [S26]

No candidate MCP endpoint was contacted. A vendor page, Registry record, or standards document was treated as published evidence only; no candidate endpoint was initialized or probed.

### Candidate matrix

The matrix below reports the **strongest published classification**. A later UNKNOWN does not erase an earlier FAIL: a candidate with a documented tools capability is ineligible regardless of whether its resource set is also published.

| # | Published identity and version | Evidence summary | R1 | R2 | R3 | R4 | R5 | R6 | R7 | Result |
|---|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 1 | `io.github.github/github-mcp-server` 2.3.0 | Official Registry publishes HTTPS remote `https://api.githubcopilot.com/mcp/` and an `Authorization` header. GitHub documents toolsets and says read-only mode “only offer[s] read-only tools.” [S7] [S8] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 2 | `io.github.upstash/context7` 4.8.0 | Official Registry publishes HTTPS remote `https://mcp.context7.com/mcp` and bearer authentication. Its README lists `resolve-library-id` and `query-docs` under “Available Tools.” [S9] [S10] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 3 | `com.microsoft/microsoft-learn-mcp` 1.0.0 | Official Registry publishes HTTPS remote `https://learn.microsoft.com/api/mcp`. The official repository documents `microsoft_docs_search`, `microsoft_docs_fetch`, and `microsoft_code_sample_search` and directs clients to `tools/list`. [S11] [S12] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 4 | `com.entityreach/public-resources` 1.0.0 | Official Registry publishes HTTPS remote `https://entityreach.com/api/public-mcp`. Vendor documentation says the public endpoint “always exposes only the three public tools.” [S13] [S14] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 5 | `be.dossierbel/public-resources` 1.1.0 | Official Registry publishes HTTPS remote `https://mcp.dossierbel.be/mcp`. The publisher's public status document reports `tools: 17`; “public resources” describes the content, not the MCP primitive. [S15] [S16] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 6 | `io.aviationresources/aviation-resources` 7.3.2 | Official Registry publishes HTTPS remote `https://api.aviationresources.io/mcp`. Vendor documentation names four tools and directs clients to `tools/list`. [S17] [S18] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 7 | `com.agentresourcemarket/agent-resource-market` 0.2.0 | Official Registry publishes HTTPS remote `https://agentresourcemarket.com/api/mcp`. Vendor documentation says it “offers only two read-only tools,” `search_resources` and `get_resource`. [S19] [S20] | PASS | PASS | PASS | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |
| 8 | `io.github.Albertito-AI/research-resource-agent` 1.1.2 | Official Registry publishes HTTPS remote `https://albert-agent-network.travelingbert.chatgpt.site/api/mcp`. The vendor page discusses a resource navigator and local agent tools but does not publish the hosted server's capability response or resource URI set. [S21] [S22] | PASS | PASS | PASS | UNKNOWN | UNKNOWN | UNKNOWN | PASS | Inconclusive |
| 9 | `aero.avioverse/library` 1.0.0 | Official Registry publishes HTTPS remote `https://avioverse.aero/mcp` and describes a read-only EASA library. The vendor page publishes the library's content but no MCP capability response, resource URI set, or fingerprint. [S23] [S24] | PASS | PASS | PASS | UNKNOWN | UNKNOWN | UNKNOWN | PASS | Inconclusive |
| 10 | `awslabs.aws-documentation-mcp-server` (official vendor project; no matching latest Registry identity found) | The official project documents only stdio installation and six tools: `read_documentation`, `search_documentation`, `read_sections`, `search_table`, `recommend`, and `get_available_services`. [S25] [S26] | **FAIL** | **FAIL** | **FAIL** | **FAIL** | UNKNOWN | UNKNOWN | PASS | Ineligible |

Rule meanings: R1 HTTPS; R2 public host; R3 clean URL; R4 resources and no tools; R5 enumerable same-origin resources; R6 stable advertised set/fingerprint; R7 credentials outside URL. For rule 2, the D1-I1 implementation rejects prohibited literal addresses and local suffixes but does not resolve DNS, so PASS here means “no prohibited literal/suffix in the published identity,” not a live reachability assertion. For rule 7, the published remote identity has no query/userinfo/fragment; where the Registry documents a header, authentication is outside the URL. [S1]

### Counts

- **Candidates examined:** 10.
- **Compatible candidates:** 0.
- **Candidates with at least one FAIL:** 8.
- **Candidates with no FAIL but UNKNOWN:** 2 (`research-resource-agent`, `aero.avioverse/library`).
- **Rule 1 failures:** 1 (AWS documentation is stdio-only).
- **Rule 2 failures:** 1 (AWS documentation has no remote host because it is stdio-only).
- **Rule 3 failures:** 1 (AWS documentation has no remote HTTPS identity to validate).
- **Rule 4 failures:** 8; the remaining two are UNKNOWN, not PASS.
- **Rule 5 failures:** 0; all ten are UNKNOWN.
- **Rule 6 failures:** 0; all ten are UNKNOWN.
- **Rule 7 failures:** 0.

### Unknown-candidate evidence gaps

The two non-FAIL candidates remain inadmissible because UNKNOWN is not PASS.

For `io.github.Albertito-AI/research-resource-agent` 1.1.2, the missing published evidence is: (1) the hosted server's capability response showing `resources` and no `tools`; (2) the complete advertised resource URI set, including proof that every URI is HTTPS and same-origin with `https://albert-agent-network.travelingbert.chatgpt.site`; and (3) a published versioned snapshot/fingerprint or stability policy sufficient to evaluate the no-churn condition. The vendor page's “resource” terminology and references to local agent tools do not establish the hosted primitive surface. [S21] [S22]

For `aero.avioverse/library` 1.0.0, the missing published evidence is: (1) a capability response showing `resources` and no `tools`; (2) the complete advertised resource URI set, including proof that every URI is HTTPS and same-origin with `https://avioverse.aero`; and (3) a published versioned snapshot/fingerprint or stability policy sufficient to evaluate the no-churn condition. “Read-only” in the Registry description proves neither primitive type nor URI shape. [S23] [S24]

## Fix

No code fix is appropriate. The evidence-backed fix is to stop D1-I2 before it creates a transport around an unidentified or incompatible server.

**Recommendation: DEFER D1-I2 and keep D1 in BACKLOG.** Do not select a candidate, do not install the MCP SDK, and do not add a server configuration from this survey. A future implementation batch may proceed only when one published candidate has affirmative evidence for all seven rules and the owner separately chooses its product content.

The decision does not reject MCP as a class. D1-R's resources-only boundary remains valid. This survey finds no published candidate that currently satisfies that boundary. Eight examined servers are ruled out by published tool/transport evidence; two are not ruled out but remain UNKNOWN on the decisive resource, capability, and stability evidence. In particular, the GitHub `--read-only` comparison does not rescue that candidate: GitHub says the mode still offers read-only tools, and tool support requires the `tools` capability. [S7] [S8]

The owner still owes a separate product decision, even if a later candidate becomes technically compatible: **is the content this server publishes something STEWARD should read?** This survey intentionally does not answer that question. FAA, Microsoft, AWS, GitHub, legal scholarship, EASA regulations, company research, and other reference corpora have different utility, trust, licensing, privacy, relevance, and operating-cost profiles. Technical admissibility does not decide product value.

### Conditions to reopen D1-I2

A future survey may reconsider a candidate when the publisher supplies all of the following:

1. a versioned capability response showing `resources` and no `tools` (or equivalent normative primitive-surface evidence);
2. the complete advertised resource URI set, proving HTTPS and same effective origin as the pinned identity;
3. a versioned snapshot/fingerprint or stability policy sufficient to evaluate the no-churn condition between reads;
4. authentication documentation showing credentials are carried outside the URL, if authentication exists;
5. a reviewed TLS identity/pin and the exact remote identity to admit; and
6. an owner product decision that the published content is useful to STEWARD.

Until those conditions are met for one server, implementation would add dependency, network, protocol, and content-injection surfaces without a known admissible resource source.

## Impact

- **Runtime:** unchanged. No MCP client, transport, SDK dependency, server configuration, tool, resource, chat path, or provider call was added.
- **D1:** remains BACKLOG. D1-I2 is deferred by this survey; D1-I1, D1-R, and D1-DEP remain unchanged.
- **Dependencies:** unchanged. The reviewed `mcp==2.3.0` selection remains a future D1-I2 prerequisite, not an installation authorization.
- **Security:** unchanged. The existing admission core continues to reject query-bearing URLs and any advertised tools capability; no remote content is admitted.
- **Operational cost:** no new network traffic, server credential, upstream availability dependency, or content-governance burden was created.
- **Documentation:** `docs/mcp_server_survey.md` records the decision, and `PLAN.md` records the survey outcome and one changelog entry.
- **Push state:** this survey does not push. The final commit SHA is reported in the handoff after commit creation. `PLAN.md` cannot truthfully contain the SHA of the commit that contains that same `PLAN.md` file: inserting it would change the commit and therefore its SHA. The one-commit gate takes precedence, and no placeholder SHA is recorded as if it were factual.

## Tests

This documentation-only batch adds no automated test because it changes no executable behavior. Research verification consisted of:

- reading the official Registry API specification and the standard `server.json` schema;
- reading SEP-2127 and the server-card schema, including the normative primitive-exclusion statement;
- reading the MCP tools specification's capability requirement;
- querying only the official Registry API for candidate identities and exact latest-version metadata;
- reading first-party vendor documentation for each retained candidate; and
- reconciling each compatibility claim to the source register below.

No candidate MCP endpoint was contacted, initialized, probed, or listed from. The survey does not claim live protocol compatibility.

## Gates

The survey is acceptable only if:

1. all seven D1-I1 rules are restated and applied to every examined candidate;
2. every compatibility classification has a cited source;
3. each UNKNOWN candidate states exactly what published evidence is missing;
4. compatible and incompatible candidate counts are explicit;
5. the recommendation is evidence-backed and does not select product content for the owner;
6. D1 remains BACKLOG;
7. no runtime, dependency, configuration, or protected-state change is present; and
8. the documentation acceptance commands are green.

The acceptance commands are recorded in the closing commit body. `PLAN.md` records the outcome and changelog entry in the same documentation-only commit.

### Source register

| ID | Exact source |
|---|---|
| S1 | [`agents/mcp_resource_core.py`](../agents/mcp_resource_core.py), especially `_canonical_https_url`, `_normalized_capabilities`, `MCPResourceAdmissionCore.admit`, and `_verify_fingerprint` |
| S2 | [Official MCP Registry API OpenAPI](https://github.com/modelcontextprotocol/registry/blob/main/docs/reference/api/openapi.yaml), especially `/v0.1/servers`, `version=latest`, pagination, `Server`, and publisher-provided `_meta` |
| S3 | [Official MCP Registry `server.json` schema, 2025-12-11](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json) |
| S4 | [SEP-2127: MCP Server Cards — HTTP Server Discovery](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/5c8483d511d60ef1f8ded5160c5290fd8213d19e/docs/seps/2127-mcp-server-cards.mdx) and [server-card schema source](https://github.com/modelcontextprotocol/ext-server-card/blob/main/schema.ts) |
| S5 | [MCP 2025-06-18 server tools specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-06-18/server/tools.mdx), “Capabilities” |
| S6 | [MCP 2025-06-18 server resources specification](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-06-18/server/resources.mdx) |
| S7 | [Official Registry metadata: `io.github.github/github-mcp-server` 2.3.0](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.github%2Fgithub-mcp-server/versions/2.3.0) |
| S8 | [Official GitHub MCP Server README](https://github.com/github/github-mcp-server/blob/main/README.md), “Toolset configuration,” “Using Toolsets,” and “Read-Only Mode” |
| S9 | [Official Registry metadata: `io.github.upstash/context7` 4.8.0](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.upstash%2Fcontext7/versions/4.8.0) |
| S10 | [Official Context7 README](https://github.com/upstash/context7/blob/master/README.md), remote setup and “Available Tools” |
| S11 | [Official Registry metadata: `com.microsoft/microsoft-learn-mcp` 1.0.0](https://registry.modelcontextprotocol.io/v0.1/servers/com.microsoft%2Fmicrosoft-learn-mcp/versions/1.0.0) |
| S12 | [Official Microsoft Learn MCP Server README](https://github.com/MicrosoftDocs/mcp/blob/main/README.md), endpoint, tool table, and dynamic tool discovery |
| S13 | [Official Registry metadata: `com.entityreach/public-resources` 1.0.0](https://registry.modelcontextprotocol.io/v0.1/servers/com.entityreach%2Fpublic-resources/versions/1.0.0) |
| S14 | [EntityReach MCP vendor documentation](https://entityreach.com/docs/mcp), “Available tools” and public-endpoint section |
| S15 | [Official Registry metadata: `be.dossierbel/public-resources` 1.1.0](https://registry.modelcontextprotocol.io/v0.1/servers/be.dossierbel%2Fpublic-resources/versions/1.1.0) |
| S16 | [DossierBel publisher status document](https://mcp.dossierbel.be/) |
| S17 | [Official Registry metadata: `io.aviationresources/aviation-resources` 7.3.2](https://registry.modelcontextprotocol.io/v0.1/servers/io.aviationresources%2Faviation-resources/versions/7.3.2) |
| S18 | [Aviation Resources MCP vendor documentation](https://aviationresources.io/mcp/), including “For developers” |
| S19 | [Official Registry metadata: `com.agentresourcemarket/agent-resource-market` 0.2.0](https://registry.modelcontextprotocol.io/v0.1/servers/com.agentresourcemarket%2Fagent-resource-market/versions/0.2.0) |
| S20 | [Agent Resource Market MCP vendor quickstart](https://agentresourcemarket.com/mcp-quickstart.md), “Public read-only MCP access” |
| S21 | [Official Registry metadata: `io.github.Albertito-AI/research-resource-agent` 1.1.2](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Albertito-AI%2Fresearch-resource-agent/versions/1.1.2) |
| S22 | [Research Resource Agent vendor page](https://alberttansinhon.com/for-agents/) |
| S23 | [Official Registry metadata: `aero.avioverse/library` 1.0.0](https://registry.modelcontextprotocol.io/v0.1/servers/aero.avioverse%2Flibrary/versions/1.0.0) |
| S24 | [Avioverse EASA library vendor page](https://avioverse.aero/regulations) |
| S25 | [Official AWS Documentation MCP Server README](https://github.com/awslabs/mcp/blob/main/src/aws-documentation-mcp-server/README.md), installation transports and “Tools” |
| S26 | Official Registry API `version=latest` name searches for `resource`, `library`, `knowledge`, `documentation`, `reference`, `aws-documentation-mcp-server`, `awslabs`, and `documentation-mcp`, queried 2026-11-26; representative exact query: [`search=aws-documentation-mcp-server`](https://registry.modelcontextprotocol.io/v0.1/servers?search=aws-documentation-mcp-server&version=latest&limit=100) |

### Final decision

**DEFER D1-I2. Keep D1 in BACKLOG. Compatible published candidates: 0 of 10 examined.**

This is a documented, evidence-backed defer rather than an absence of work. The survey establishes which surveyed candidates are inadmissible, identifies the exact evidence still missing for the two inconclusive candidates, and prevents implementation from creating a resource path around a server that exposes tools or lacks proven resource semantics.