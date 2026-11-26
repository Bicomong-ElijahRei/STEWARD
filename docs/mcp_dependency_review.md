# STEWARD D1-DEP — MCP dependency and protocol review

**Status:** design decision only; no dependency was installed and no MCP transport or runtime was implemented

**Review date:** 2026-11-26

**Decision:** confirm the official MCP Python SDK at `mcp==2.3.0` for a future D1-I2 implementation, subject to the exact-version, hash-lock, advisory-remediation, and import-boundary conditions in this review; D1 remains BACKLOG

## 1. Scope, non-goals, and preserved decisions

This review resolves the exact official-SDK dependency decision required by the D1-R integration safety review and the D1-I1 admission core. D1-R selected the official SDK because a protocol client must correctly own JSON-RPC framing, content negotiation, session/version behavior, and hostile transport input; D1-I1 established a standard-library-only, transport-agnostic admission boundary. This batch does not reverse either decision. It selects the reviewed SDK release and defines the dependency closure that a later D1-I2 implementation may install. [S1] [S2] [S3]

This is a **read-only dependency review**. It does not add `mcp` to `requirements.txt`, change the existing `cryptography` pin, install packages, write a lock file, create a client, connect to a server, add configuration, or expose a resource to chat. The current requirement set still contains `cryptography==43.0.1` and `requests==2.32.3`, while `mcp` is not installed in the active Python 3.12 environment. [S4] [S5] [S6]

Preserved from D1-R:

- one explicitly admitted, identity-pinned, read-only remote MCP **resource** server;
- no invokable tools, stdio, local MCP resources, or MCP-caused local mutation;
- remote content never enters supervisor routing or native tool context;
- exact version/hash/license/advisory review before dependency installation; and
- bounded deadlines, result sizes, cancellation, and failure isolation.

Those are integration and safety decisions, not dependency-selection details. Nothing in this review broadens them. [S1]

## 2. Method, environment, and reproducibility

The review environment is Windows x64, CPython **3.12.10**, and pip **25.0.1**. The repository was clean before editing; `HEAD` and `origin/main` were both `78a88b645a249e9537b05ba30baecb68398b279d` on branch `main`. The preflight also confirmed `git diff --check` exited successfully. [S7]

The closure was resolved without installation using:

1. `python -m pip install --dry-run --only-binary=:all: --ignore-installed --report <temporary-json>` for `mcp==2.3.0` together with the remediated `cryptography==50.0.2`;
2. a second non-ignored dry run to measure the delta against the active environment; and
3. PyPI release JSON and wheel metadata for exact requirements, artifact names, SHA-256 digests, upload dates, licenses, and PyPI ownership roles.

No report or helper script was retained in the repository, and the temporary report was removed outside the repository after use. The resolved closure contains **29 packages**. Against the current environment, MCP alone would add seven packages—`PyJWT`, `mcp`, `mcp-types`, `python-multipart`, `pywin32`, `sse-starlette`, and `starlette`—while retaining the existing but vulnerable `cryptography==43.0.1`; the remediated resolution additionally upgrades `cryptography` to `50.0.2`. [S4] [S5] [S8]

Advisories were queried against the OSV API by exact PyPI package/version for all 29 reviewed versions, plus a separate exact query for the current `cryptography==43.0.1`. A database miss is evidence of no **recorded** OSV entry at the review time, not proof that a package has no defect. [S9]

## 3. Protocol surface the dependency must cover

A resources-only client is still a real MCP client. It must send JSON-RPC 2.0 requests, correlate request IDs, distinguish responses from notifications and server requests, preserve JSON-RPC error objects, and enforce bounds on untrusted metadata and content. JSON-RPC permits requests, notifications, responses, batches, and standard error codes; MCP constrains how those messages are carried over its transports. [S10] [S11]

For the current **2026-07-28** protocol revision, the SDK distinguishes the modern stateless/per-request-envelope era from handshake-era revisions. SDK v2.3.0 knows protocol versions `2024-11-05`, `2025-03-26`, `2025-06-18`, `2025-11-25`, and `2026-07-28`; the first four are handshake versions and `2026-07-28` is the modern version. The modern flow probes with `server/discover`; the legacy flow negotiates through `initialize` and `notifications/initialized`. [S12] [S13]

The modern Streamable HTTP transport requires POST for JSON-RPC messages, an `Accept` header offering both `application/json` and `text/event-stream`, and support for either a JSON response or an SSE response. Its per-request metadata carries protocol/client information. Older handshake-era Streamable HTTP could mint an `Mcp-Session-Id`, required clients to send `MCP-Protocol-Version` on subsequent HTTP requests, allowed a standalone GET SSE stream for server messages, used HTTP DELETE to terminate a session, and supported `Last-Event-ID` stream resumption. The deprecated 2024-11-05 HTTP+SSE transport used separate SSE and message endpoints. [S14] [S15] [S16]

Resource discovery and retrieval use `resources/list` and `resources/read`. A modern server that advertises `resources.listChanged` should notify capable clients when the list changes; a legacy server should send `notifications/resources/list_changed`. Notification delivery is not a substitute for the D1-I1 control: STEWARD must re-verify the admitted SHA-256 resource fingerprint immediately before each read and refuse a changed snapshot. A narrow client may ignore change notifications only because that independent re-verification remains authoritative. [S17] [S18] [S19]

These requirements make “just call three JSON-RPC methods over `requests`” an inaccurate description of a compliant client.

## 4. Candidate A — official `mcp==2.3.0` (selected)

The official Python SDK is the `modelcontextprotocol/python-sdk` project published as `mcp`; v2.3.0 declares CPython `>=3.10`, MIT licensing, and direct dependencies including `httpx2`, `jsonschema`, exact `mcp-types==2.3.0`, OpenTelemetry API, Pydantic, `pyjwt[crypto]`, multipart parsing, Windows `pywin32`, SSE-Starlette, Starlette, typing helpers, and Uvicorn. The reviewed release was uploaded to PyPI on 2026-10-02. [S2] [S20] [S21]

Advantages:

- it implements the protocol and transport compatibility matrix rather than asking STEWARD to own it;
- it supports modern discovery and legacy handshake negotiation, including the protocol-version edge cases visible in the reviewed source;
- it provides typed resource discovery/read operations and transport/session handling;
- it is maintained in the protocol project’s own SDK repository, reducing the chance that STEWARD’s client silently diverges from the specification; and
- it keeps future compatibility work with upstream rather than in STEWARD.

Costs:

- the wheel is small but the default package pulls a broad 29-package runtime closure, including server-oriented and platform-specific packages not all needed by a client-only STEWARD path;
- `mcp/__init__.py` eagerly imports client, server, and stdio symbols, so upstream’s module graph is not structurally client-only;
- the project must still wrap the SDK with D1-I1 admission, identity pinning, bounds, redaction, cancellation, and route isolation; and
- adopting a fast-moving SDK creates an update obligation.

Those costs are acceptable because dependency size alone is not a reason to reimplement a standards protocol. The selected controls are to import only client APIs in application code, never configure or invoke stdio, and prove that no stdio/process-launch path is reachable. A literal assertion that the upstream stdio module can never appear in `sys.modules` would be false because of eager package initialization; the enforceable boundary is no application reference, configuration, invocation, or reachable process launch. [S22]

## 5. Candidate B — narrow client over existing `requests` (rejected)

A hand-written client could use the already-declared `requests==2.32.3` and implement only initialization/discovery, `resources/list`, and `resources/read`. It would avoid MCP’s 29-package closure. However, that implementation is not small transport glue: it must own JSON-RPC IDs and errors, modern versus legacy negotiation, both JSON and SSE response modes, `Accept` negotiation, origin-safe HTTP behavior, optional session IDs, protocol headers, GET/DELETE lifecycle, reconnect and `Last-Event-ID` behavior, notifications, malformed frames, and compatibility with a changing protocol. [S10] [S14] [S15]

It also inherits current dependency risk: OSV reports two advisories affecting `requests==2.32.3`—malicious-URL `.netrc` credential disclosure (`GHSA-9hjg-9r4m-mvj7`, fixed in 2.32.4) and insecure temporary-file reuse in `extract_zipped_paths()` (`GHSA-gc5v-m9x4-r6x2`, fixed in 2.33.0). Thus “no new dependency” would not mean “no dependency remediation.” [S23] [S24]

**Engineering estimate (not an upstream measurement):** a production-quality modern-only narrow client would still be roughly 500–900 lines plus a larger hostile-transport test suite; dual modern/legacy compatibility, session termination, and resumable SSE would materially increase both. STEWARD would own every future protocol revision and each interoperability defect. That long-term correctness and maintenance burden outweighs the narrower closure, so Candidate B is rejected. [S1]

## 6. Candidate C — transport helpers or a smaller third-party client (rejected)

`httpx-sse==0.4.3` is an SSE consumer for HTTPX, not an MCP protocol implementation. It can reduce SSE parsing code but does not supply JSON-RPC correlation, MCP lifecycle/version behavior, resource semantics, or session handling. Adding it beside the SDK-selected `httpx2` stack would increase rather than clarify the dependency graph. [S25]

PyPI’s `mcp-client==0.0.0` is not a usable candidate: its metadata requires Python `>=3.13` (incompatible with CPython 3.12 here), declares no useful license expression, has no dependencies, and its wheel contains only an empty `mcp_client` package plus packaging metadata—no MCP client implementation. It is an unreviewable placeholder, not an alternative SDK. [S26]

A native, service-specific adapter remains the preferred alternative for a different concrete product integration, but it is not D1 because it does not satisfy “one real MCP server usable from chat.” This preserves the D1-R distinction between selecting a dependency for MCP and reconsidering whether the feature should be MCP at all. [S1]

## 7. Complete resolved dependency closure

The following is the complete binary-only closure resolved for CPython 3.12/Windows x64 from `mcp==2.3.0` with the remediated `cryptography==50.0.2`. “Direct” means declared by `mcp`; all other rows are transitive. Optional extras and sdists are not part of the reviewed lock. Exact PyPI release metadata is linked for each package in §8. [S2] [S8] [S27] [S28]

| Package | Role | Reviewed artifact | SHA-256 |
|---|---|---|---|
| `mcp==2.3.0` | direct | `mcp-2.3.0-py3-none-any.whl` | `dd0c44c089d16453e8ae31a3877a0054d7a2314caaa81f5e0541b9b1734b2377` |
| `mcp-types==2.3.0` | direct | `mcp_types-2.3.0-py3-none-any.whl` | `968efdbdaedfab06adae40d378a34395f1090c5921d4be3c9cde283aaf76d91d` |
| `anyio==4.16.0` | direct | `anyio-4.16.0-py3-none-any.whl` | `c66ae634e0b8228396b801741beb3294326d4b6102f7bba4041c0dfb58c29026` |
| `httpx2==2.16.2` | direct | `httpx2-2.16.2-py3-none-any.whl` | `f05c13aade4c45dbf1c9060647a1058f0acad62398fad96e741269edb33d46f5` |
| `jsonschema==4.26.0` | direct | `jsonschema-4.26.0-py3-none-any.whl` | `d489f15263b8d200f8387e64b4c3a75f06629559fb73deb8fdfb525f2dab50ce` |
| `opentelemetry-api==1.45.2` | direct | `opentelemetry_api-1.45.2-py3-none-any.whl` | `2cbd737377e710ee740d261c94e93fa0f08e6d037c18f17513cc0a2d94479a34` |
| `pydantic==2.14.4` | direct | `pydantic-2.14.4-py3-none-any.whl` | `653a2ad9f6d8858529c77c72717d0ea991d6c6837fe683246b2f4b2bbfc3fadc` |
| `PyJWT==2.15.1` | direct | `pyjwt-2.15.1-py3-none-any.whl` | `42d59d631f7768a1028a64c7ff581a9bf7519804daf91fc5b6c56e30eec5e193` |
| `python-multipart==0.0.34` | direct | `python_multipart-0.0.34-py3-none-any.whl` | `ebacd224bd686eee2f9aa1066a657affe07435a185834e05e5235e2e59173e91` |
| `pywin32==312` | direct (Windows) | `pywin32-312-cp312-cp312-win_amd64.whl` | `b457f6d628a47e8a7346ce22acb7e1a46a4a78b52e1d17e1af56871bd19a93bc` |
| `sse-starlette==3.7.1` | direct | `sse_starlette-3.7.1-py3-none-any.whl` | `c1bb3af0508c6c24cd4ab6257047654bbec01456a424bed36b36e8020cd7a37f` |
| `starlette==1.10.0` | direct | `starlette-1.10.0-py3-none-any.whl` | `478c0ab3b4ced6e82719849c118fa406f0278a3499c1a898cd15cd31bdc38ce4` |
| `typing-extensions==4.16.0` | direct | `typing_extensions-4.16.0-py3-none-any.whl` | `481caa481374e813c1b176ada14e97f1f67a4539ce9cfeb3f350d78d6370c2e8` |
| `typing-inspection==0.4.5` | direct | `typing_inspection-0.4.5-py3-none-any.whl` | `bc210535442b39e1bf2805e0c7a17dfd6a4ace760c84c7f7d16245d23a6b1c39` |
| `uvicorn==0.54.0` | direct | `uvicorn-0.54.0-py3-none-any.whl` | `505bdb0f318731d45f1f712071fc781a8981f6847a31c902c9f5e652d4f67faf` |
| `httpcore2==2.16.2` | transitive | `httpcore2-2.16.2-py3-none-any.whl` | `16051ae2a42f776007543f32de9349a317b23d2cbb4e1456b4bac0e88b87419a` |
| `idna==3.20` | transitive | `idna-3.20-py3-none-any.whl` | `ab7ae7122974553370f0bdb919e1a960b2cd1bc1ef0276416d896db81c14582c` |
| `truststore==0.10.5` | transitive | `truststore-0.10.5-py3-none-any.whl` | `9aaaedaefaf06d8b206278cf8b5012bc897f485a874503501e12d776df78951c` |
| `h11==0.16.0` | transitive | `h11-0.16.0-py3-none-any.whl` | `63cf8bbe7522de3bf65932fda1d9c2772064ffb3dae62d55932da54b31cb6c86` |
| `attrs==26.1.0` | transitive | `attrs-26.1.0-py3-none-any.whl` | `c647aa4a12dfbad9333ca4e71fe62ddc36f4e63b2d260a37a8b83d2f043ac309` |
| `jsonschema-specifications==2025.9.1` | transitive | `jsonschema_specifications-2025.9.1-py3-none-any.whl` | `98802fee3a11ee76ecaca44429fda8a41bff98b00a0f2838151b113f210cc6fe` |
| `referencing==0.37.0` | transitive | `referencing-0.37.0-py3-none-any.whl` | `381329a9f99628c9069361716891d34ad94af76e461dcb0335825aecc7692231` |
| `rpds-py==2026.9.1` | transitive | `rpds_py-2026.9.1-cp312-cp312-win_amd64.whl` | `5ce8943f79c2210f7abcc28e86367b03b28d95027fd01c46d2472373ae70c86f` |
| `annotated-types==0.8.0` | transitive | `annotated_types-0.8.0-py3-none-any.whl` | `f072f4d804ea359e4eaf198b1af7a8b0943881a87f31bb764f8bf219bb9419e0` |
| `pydantic-core==2.50.5` | transitive | `pydantic_core-2.50.5-cp312-cp312-win_amd64.whl` | `baa107902f8e38011a5f79836d905eb6bfaac1d4b0bd09fc86509b711d0b09c8` |
| `cryptography==50.0.2` | transitive (`PyJWT[crypto]`) | `cryptography-50.0.2-cp311-abi3-win_amd64.whl` | `7afa5a6602a9f29af1f3a2965f831bae7c9d5d597b7cbb716d41ab3b7d89879c` |
| `cffi==2.1.1` | transitive | `cffi-2.1.1-cp312-cp312-win_amd64.whl` | `f53e442b08449d42821fa4a4fba000095af9f62742a500f978a9f557ec44339a` |
| `pycparser==3.12` | transitive | `pycparser-3.12-py3-none-any.whl` | `a076f3f489b39b43ed13563a1dafe42447445bec2e294154ec5c57fcdda4c85e` |
| `click==8.5.1` | transitive | `click-8.5.1-py3-none-any.whl` | `8bb5376d2006950386f8c6427613334a2acadc5f559cb80e638d00b4df957e37` |

The resolved closure is usable on the target host. `mcp` itself permits Python 3.10+, but selected `httpx2`, `python-multipart`, `rpds-py`, and `pycparser` releases require Python 3.11+, so this **platform lock** is for Python 3.11/3.12 rather than a universal Python 3.10 lock. `pywin32` is selected only on Windows. The currently resolved project version `pydantic==2.14.4` satisfies MCP’s `pydantic>=2.12.0` requirement and ChromaDB’s `pydantic>=2.0`; no Pydantic downgrade is required. [S2] [S29]

## 8. Licenses, ownership, release dates, and advisory status

The closure uses permissive, OSI-style licenses: MIT, MIT-0, BSD-3-Clause, Apache-2.0, PSF/PSF-2.0, and `Apache-2.0 OR BSD-3-Clause` for `cryptography`. No copyleft or source-available license was found in the reviewed release metadata. License metadata is evidence for review, not legal advice; redistribution obligations, if any, must be assessed by the project owner. [S28]

The ownership column reports PyPI organization/role metadata, not an assertion that a person or organization independently audits every release. “No OSV match” means the exact-version OSV query returned no record at review time. Package links point to the exact reviewed release metadata. [S9] [S28]

| Package | License | PyPI organization / owners / maintainers | Artifact upload date | OSV |
|---|---|---|---|---|
| [`mcp==2.3.0`](https://pypi.org/pypi/mcp/2.3.0/json) | MIT | owners `dsp`, `jspahrsummers`, `maxisbey`; maintainer `Kludex` | 2026-10-02 | no match |
| [`mcp-types==2.3.0`](https://pypi.org/pypi/mcp-types/2.3.0/json) | MIT | owners `Kludex`, `dsp`, `maxisbey` | 2026-10-02 | no match |
| [`anyio==4.16.0`](https://pypi.org/pypi/anyio/4.16.0/json) | MIT | owners `Thomas.Grainger`, `Zac-HD`, `agronholm`, `njs`, `smurfix` | 2026-11-01 | no match |
| [`httpx2==2.16.2`](https://pypi.org/pypi/httpx2/2.16.2/json) | BSD-3-Clause | organization `pydantic`; owner `Kludex` | 2026-11-16 | no match |
| [`jsonschema==4.26.0`](https://pypi.org/pypi/jsonschema/4.26.0/json) | MIT | organization `jsonschema` | 2026-01-07 | no match |
| [`opentelemetry-api==1.45.2`](https://pypi.org/pypi/opentelemetry-api/1.45.2/json) | Apache-2.0 | organization `opentelemetry`; owner `LeightonC` | 2026-10-29 | no match |
| [`pydantic==2.14.4`](https://pypi.org/pypi/pydantic/2.14.4/json) | MIT | organization `pydantic`; maintainers `dmontagu`, `samuelcolvin` | 2026-11-19 | no match |
| [`PyJWT==2.15.1`](https://pypi.org/pypi/PyJWT/2.15.1/json) | MIT | owner `jpadilla` | 2026-09-28 | no match |
| [`python-multipart==0.0.34`](https://pypi.org/pypi/python-multipart/0.0.34/json) | Apache-2.0 | owner `Kludex` | 2026-11-16 | no match |
| [`pywin32==312`](https://pypi.org/pypi/pywin32/312/json) | PSF | owner `mhammond`; maintainers `glyph`, `pf_moore` | 2026-06-04 | no match |
| [`sse-starlette==3.7.1`](https://pypi.org/pypi/sse-starlette/3.7.1/json) | BSD-3-Clause | owner `sysid` | 2026-11-22 | no match |
| [`starlette==1.10.0`](https://pypi.org/pypi/starlette/1.10.0/json) | BSD-3-Clause | owner `Kludex` | 2026-10-24 | no match |
| [`typing-extensions==4.16.0`](https://pypi.org/pypi/typing-extensions/4.16.0/json) | PSF-2.0 | owners `JelleZijlstra`, `guido`, `jukkal`; maintainers `hauntsaninja`, `ilevkivskyi`, `srittau` | 2026-07-02 | no match |
| [`typing-inspection==0.4.5`](https://pypi.org/pypi/typing-inspection/0.4.5/json) | MIT | organization `pydantic` | 2026-11-04 | no match |
| [`uvicorn==0.54.0`](https://pypi.org/pypi/uvicorn/0.54.0/json) | BSD-3-Clause | owner `Kludex` | 2026-09-25 | no match |

| Package | License | PyPI organization / owners / maintainers | Artifact upload date | OSV |
|---|---|---|---|---|
| [`httpcore2==2.16.2`](https://pypi.org/pypi/httpcore2/2.16.2/json) | BSD-3-Clause | organization `pydantic`; owner `Kludex` | 2026-11-16 | no match |
| [`idna==3.20`](https://pypi.org/pypi/idna/3.20/json) | BSD-3-Clause | owner `kjd` | 2026-09-17 | no match |
| [`truststore==0.10.5`](https://pypi.org/pypi/truststore/0.10.5/json) | MIT | owners `SethMichaelLarson`, `davisagli` | 2026-10-12 | no match |
| [`h11==0.16.0`](https://pypi.org/pypi/h11/0.16.0/json) | MIT | owner `njs`; maintainer `pgjones` | 2025-04-24 | no match |
| [`attrs==26.1.0`](https://pypi.org/pypi/attrs/26.1.0/json) | MIT | organization `attrs` | 2026-03-19 | no match |
| [`jsonschema-specifications==2025.9.1`](https://pypi.org/pypi/jsonschema-specifications/2025.9.1/json) | MIT | organization `jsonschema` | 2025-09-08 | no match |
| [`referencing==0.37.0`](https://pypi.org/pypi/referencing/0.37.0/json) | MIT | organization `jsonschema` | 2025-10-13 | no match |
| [`rpds-py==2026.9.1`](https://pypi.org/pypi/rpds-py/2026.9.1/json) | MIT | owner `Julian` | 2026-10-04 | no match |
| [`annotated-types==0.8.0`](https://pypi.org/pypi/annotated-types/0.8.0/json) | MIT | owners `Zac-HD`, `adriangb` | 2026-07-23 | no match |
| [`pydantic-core==2.50.5`](https://pypi.org/pypi/pydantic-core/2.50.5/json) | MIT | organization `pydantic`; owners `dmontagu`, `samuelcolvin` | 2026-11-19 | no match |
| [`cryptography==50.0.2`](https://pypi.org/pypi/cryptography/50.0.2/json) | Apache-2.0 OR BSD-3-Clause | organization `pyca`; owner `reaperhulk` | 2026-09-30 | no match |
| [`cffi==2.1.1`](https://pypi.org/pypi/cffi/2.1.1/json) | MIT-0 | owners `Armin.Rigo`, `fijal`, `mattclay`, `nitzmahone`; maintainers `alexgaynor`, `glyph`, `odidev`, `reaperhulk` | 2026-08-03 | no match |
| [`pycparser==3.12`](https://pypi.org/pypi/pycparser/3.12/json) | BSD-3-Clause | owner `eliben` | 2026-10-22 | no match |
| [`click==8.5.1`](https://pypi.org/pypi/click/8.5.1/json) | BSD-3-Clause | organization `pallets` | 2026-11-06 | no match |

## 9. Cryptography advisory remediation

MCP’s `pyjwt[crypto]>=2.10.1` dependency ultimately permits `cryptography>=3.4.0`. That compatibility floor is not a safe STEWARD pin. The project’s current `cryptography==43.0.1` is affected by six distinct advisory records (OSV returns ten records because four advisories also have PYSEC aliases). The reviewed fixed versions are: [S30] [S31] [S32] [S33] [S34] [S35]

| Advisory | Alias / issue | First reviewed fixed release |
|---|---|---|
| [`GHSA-79v4-65xg-pq4g`](https://osv.dev/vulnerability/GHSA-79v4-65xg-pq4g) | `CVE-2024-12797`; vulnerable OpenSSL included in cryptography wheels | `44.0.1` |
| [`GHSA-r6ph-v2qm-q3c2`](https://osv.dev/vulnerability/GHSA-r6ph-v2qm-q3c2) | `CVE-2026-26007`; missing subgroup validation for SECT curves | `46.0.5` |
| [`GHSA-m959-cc7f-wv43`](https://osv.dev/vulnerability/GHSA-m959-cc7f-wv43) | `CVE-2026-34073`; incomplete DNS name-constraint enforcement on peer names | `46.0.6` |
| [`GHSA-537c-gmf6-5ccf`](https://osv.dev/vulnerability/GHSA-537c-gmf6-5ccf) | vulnerable OpenSSL included in cryptography wheels | `48.0.1` |
| [`GHSA-jwv3-5hgf-82ww`](https://osv.dev/vulnerability/GHSA-jwv3-5hgf-82ww) | `CVE-2026-69249`; duplicate self-signed intermediates can cause exponential path building | `49.0.0` |
| [`GHSA-m2h6-j472-rp4c`](https://osv.dev/vulnerability/GHSA-m2h6-j472-rp4c) | `CVE-2026-69248`; wildcard DNS names can escape `permittedSubtrees` | `49.0.0` |

The highest first-fixed release among those records is `49.0.0`. The reviewed lock uses the later current release `cryptography==50.0.2`, whose exact-version OSV query returned no record. **Future D1-I2 remediation floor:** replace `cryptography==43.0.1` with `cryptography==50.0.2`; do not solve the issue by merely adding `mcp==2.3.0`, because pip would otherwise retain the project’s vulnerable 43.0.1 pin. [S4] [S8] [S9]

This batch does not make that replacement because the task prohibits dependency changes or installation. The update belongs in D1-I2, where it must be installed and tested together with the SDK.

## 10. Transport, import, and runtime implications

The selected SDK’s client transport is a material part of the dependency decision, not an interchangeable implementation detail. D1-I2 should use the SDK’s Streamable HTTP client path against the one admitted HTTPS origin. It must not use stdio. The SDK’s reviewed Streamable HTTP source contains origin-constrained requests, protocol-version handling, session termination, and SSE reconnection logic; those are reasons to use the SDK rather than approximate them. They do not replace STEWARD’s D1-I1 admission core or D1-R identity, allowlist, bound, redaction, and isolation controls. [S1] [S14] [S22] [S36]

The import boundary needs a precise test formulation. Importing any `mcp.*` submodule first executes the parent `mcp/__init__.py`, which eagerly imports `stdio_client`, `stdio_server`, and server session symbols. Therefore:

- application source may import only from the SDK’s client API (directly or through a STEWARD adapter);
- application source must not reference, configure, or call `StdioServerParameters`, `stdio_client`, `stdio_server`, or any process-launch API;
- D1-I2 tests must prove that the client path cannot reach subprocess/process-launch behavior and that no stdio transport is configured;
- a test that merely asserts “`mcp.client.stdio` is absent from `sys.modules`” is invalid for the official package and must not be used.

This is stricter and more honest than claiming the upstream wheel is structurally client-only. It also preserves the D1-R policy: SDK availability does not authorize stdio, tools, local resources, or local mutation. [S1] [S22]

This review did not establish that the SDK provides a reviewed TLS public-key/certificate fingerprint pin suitable for D1-R. D1-I2 must therefore treat origin/identity pinning as an application-owned transport boundary and test it independently. Normal TLS verification, SDK origin checks, and an application-owned certificate/public-key pin are complementary controls; none authorizes a different origin. [S1] [S36]

## 11. Future D1-I2 requirement and lock plan

A future D1-I2 dependency change must make these two **direct requirement** edits:

```diff
-cryptography==43.0.1
+cryptography==50.0.2
+mcp==2.3.0
```

It must not add `httpx`, `httpx-sse`, or `mcp-client` as MCP alternatives: `mcp==2.3.0` brings `httpx2`, and the other two were rejected in §5–§6. It must not downgrade `pydantic==2.14.4`. [S2] [S25] [S26] [S29]

Because the normal requirements file pins only project-level direct dependencies, D1-I2 must also add a **platform lock artifact** for the complete 29-package closure in §7. Each package must be exact (`==`) and carry the reviewed `--hash=sha256:<digest>` value for the selected Windows CPython 3.12 x64 wheel. The lock is intentionally platform-specific; another OS, architecture, or Python version requires separately resolved and reviewed hashes rather than silently reusing these.

Before installation, D1-I2 must prove:

1. `pip install --dry-run --only-binary=:all: --require-hashes -r <platform-lock>` resolves exactly the 29 reviewed versions and no additional package;
2. the direct `requirements.txt` pins agree with the lock (`mcp==2.3.0`, `cryptography==50.0.2`);
3. a fresh isolated CPython 3.12/Windows environment installs only the reviewed wheels and passes an import/identity check;
4. the exact-version OSV query is repeated immediately before installation, and any new match blocks installation until re-reviewed; and
5. the full application test suite passes after the cryptography upgrade as well as after the SDK addition.

A lock generated later from floating SDK bounds is not acceptable unless its complete output is diffed against this review and re-reviewed. [S2] [S8] [S28]

## 12. Final decision and rationale

**DECISION: select the official `mcp==2.3.0` SDK for a future D1-I2 implementation.** D1 remains BACKLOG. This review does not install the SDK, implement a transport, integrate chat, or complete D1.

| Criterion | A: official SDK | B: narrow `requests` client | C: helper/placeholder |
|---|---|---|---|
| Protocol and version correctness | Upstream-owned and reviewed | STEWARD-owned maintenance project | Not supplied by helper/placeholder |
| Dependency surface | 29 reviewed packages | smaller HTTP stack, but protocol code remains | misleading or unusable |
| Future revision burden | upstream plus bounded STEWARD wrapper | entirely STEWARD | depends on unavailable implementation |
| Current reviewed dependency advisories | none in the 29-package closure | includes current `requests==2.32.3` advisories | `mcp-client` unusable on Python 3.12 |
| D1-R compatibility | selected, with controls | unnecessary reinvention | rejected |
| Decision | **SELECTED** | rejected | rejected |

The SDK’s breadth is a real cost, but the alternatives transfer a standards-protocol correctness and maintenance burden to STEWARD without eliminating dependency risk. The official SDK is the lower-risk choice for a one-real-server, read-only integration, provided D1-I2 honors the cryptography remediation, complete hash lock, minimal application import boundary, and D1-I1/D1-R controls. [S1] [S2] [S8] [S23] [S24]

No amendment to `docs/mcp_integration_review.md` is required: the integration decision, selected scope, official-SDK choice, and prohibition on stdio/tools/local resources remain unchanged. This document resolves only the exact SDK release and its dependency conditions.

## 13. Future D1-I2 acceptance criteria and residual limitations

D1-I2 is acceptable only if every criterion below is demonstrated:

1. `requirements.txt` contains exact direct pins `mcp==2.3.0` and `cryptography==50.0.2`; no alternative client, transport helper, or placeholder is added.
2. A Windows CPython 3.12 x64 lock contains the complete 29-package closure from §7 with exact versions and the reviewed wheel hashes; a hash-required dry run resolves no additional package.
3. The lock is installed into a fresh isolated environment, and exact-version OSV/advisory checks are repeated immediately before and after installation.
4. The application imports only the SDK client API. Tests prove no application reference/configuration of stdio and no reachable subprocess/process-launch path; no invalid `sys.modules` absence assertion is used.
5. One real remote MCP resource server is usable from chat. A tools-capable server is refused wholesale; no tool is invoked or published to the model.
6. D1-I1 remains the admission boundary: exact HTTPS origin and reviewed TLS identity, explicit resource allowlist, changed/missing/duplicate resource refusal, and SHA-256 fingerprint re-verification immediately before every read.
7. The SDK result passes through the existing immutable, bounded, redacted/truncated, retrieval-only result container with `routing_eligible=False` and `native_tool_eligible=False`.
8. JSON, SSE, malformed frame, oversized body, redirect, timeout, cancellation, session/notification, and server-failure tests prove that failures remain bounded and cannot enter supervisor routing, native tool context, the operation journal, or protected state.
9. No local MCP resource is registered or exposed; no SDK error or server content can cause a local mutation.
10. A real-server acceptance run, full test suite, validator, compile check, and diff check are green; PLAN records the actual implementation commit and any newly discovered limitation.

### 13.1 Residual limitations

- The closure is broad. D1-I2 can constrain how STEWARD uses it but cannot make the upstream wheel client-only.
- The official package’s eager top-level imports make the stdio boundary an application-call/reachability property, not a module-absence property.
- The reviewed hashes are platform-specific. A different OS, architecture, or Python version needs its own resolution and review.
- OSV is a point-in-time database and cannot prove absence of defects. Repeated pre-install checks and pinned artifacts are necessary, not sufficient.
- The SDK is moving quickly; a later SDK release is not automatically acceptable and requires a new closure/advisory comparison.
- The concrete server and resource use case remain an open D1 product choice. This review selects the dependency, not that choice.
- The D1-R TLS public-key/certificate pin mechanism remains for D1-I2 design; this review did not validate one.
- The existing `requests==2.32.3` project pin has two advisories noted in §5. D1-I2 does not need to change `requests` to use the SDK, but those pre-existing advisories should be remediated in a separate scoped dependency-maintenance change rather than silently folded into the MCP decision.

## Source register

| ID | Exact source |
|---|---|
| S1 | [`docs/mcp_integration_review.md`](mcp_integration_review.md), especially §§5, 9, 12, and 13 |
| S2 | [PyPI release metadata: `mcp==2.3.0`](https://pypi.org/pypi/mcp/2.3.0/json) |
| S3 | [`agents/mcp_resource_core.py`](../agents/mcp_resource_core.py) and D1-I1 entry in [`PLAN.md`](../PLAN.md) |
| S4 | [`requirements.txt`](../requirements.txt) |
| S5 | Local read-only command `python -m pip show mcp` (package not found), 2026-11-26 |
| S6 | Local read-only environment inventory / `python --version` / `python -m pip --version`, 2026-11-26 |
| S7 | Local git preflight: `git rev-parse HEAD`, `git rev-parse origin/main`, `git branch --show-current`, `git status --porcelain=v1`, `git diff --check`, 2026-11-26 |
| S8 | Local pip dry-run/report resolution for `mcp==2.3.0` and `cryptography==50.0.2`, 2026-11-26 (temporary report removed after reading) |
| S9 | [OSV exact-version query API](https://google.github.io/osv.dev/post-v1-query/), queried for every exact package/version in §7 and for `cryptography==43.0.1`, 2026-11-26 |
| S10 | [JSON-RPC 2.0 specification](https://www.jsonrpc.org/specification) |
| S11 | [MCP `mcp-types` v2.3.0 type definitions](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0/src/mcp-types/mcp_types) |
| S12 | [SDK v2.3.0 protocol-version registry](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp-types/mcp_types/version.py) |
| S13 | [SDK v2.3.0 client session source](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/client/session.py) |
| S14 | [MCP 2026-07-28 Streamable HTTP transport](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx) |
| S15 | [MCP 2025-11-25 transports](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/basic/transports.mdx) |
| S16 | [MCP 2026-07-28 transport compatibility with legacy revisions](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx) |
| S17 | [MCP 2026-07-28 resources](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/server/resources.mdx) |
| S18 | [MCP 2025-11-25 resources](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2025-11-25/server/resources.mdx) |
| S19 | [D1-I1 PLAN entry](../PLAN.md), BATCH D1-I1 section |
| S20 | [Official MCP Python SDK repository](https://github.com/modelcontextprotocol/python-sdk/tree/v2.3.0) |
| S21 | [SDK v2.3.0 package metadata](https://raw.githubusercontent.com/modelcontextprotocol/python-sdk/v2.3.0/pyproject.toml) |
| S22 | [SDK v2.3.0 top-level `mcp/__init__.py`](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/__init__.py) |
| S23 | [`GHSA-9hjg-9r4m-mvj7`](https://osv.dev/vulnerability/GHSA-9hjg-9r4m-mvj7) |
| S24 | [`GHSA-gc5v-m9x4-r6x2`](https://osv.dev/vulnerability/GHSA-gc5v-m9x4-r6x2) |
| S25 | [PyPI release metadata: `httpx-sse==0.4.3`](https://pypi.org/pypi/httpx-sse/0.4.3/json) |
| S26 | [PyPI release metadata: `mcp-client==0.0.0`](https://pypi.org/pypi/mcp-client/0.0.0/json) and its reviewed wheel contents |
| S27 | Local read-only inspection of the selected wheel filenames and SHA-256 digests in the temporary pip report, 2026-11-26 |
| S28 | Exact PyPI release JSON and wheel metadata linked per package in §§7–8 |
| S29 | [PyPI release metadata: `chromadb==1.5.9`](https://pypi.org/pypi/chromadb/1.5.9/json) and [`pydantic==2.14.4`](https://pypi.org/pypi/pydantic/2.14.4/json) |
| S30 | [`GHSA-79v4-65xg-pq4g`](https://osv.dev/vulnerability/GHSA-79v4-65xg-pq4g) |
| S31 | [`GHSA-r6ph-v2qm-q3c2`](https://osv.dev/vulnerability/GHSA-r6ph-v2qm-q3c2) |
| S32 | [`GHSA-m959-cc7f-wv43`](https://osv.dev/vulnerability/GHSA-m959-cc7f-wv43) |
| S33 | [`GHSA-537c-gmf6-5ccf`](https://osv.dev/vulnerability/GHSA-537c-gmf6-5ccf) |
| S34 | [`GHSA-jwv3-5hgf-82ww`](https://osv.dev/vulnerability/GHSA-jwv3-5hgf-82ww) |
| S35 | [`GHSA-m2h6-j472-rp4c`](https://osv.dev/vulnerability/GHSA-m2h6-j472-rp4c) |
| S36 | [SDK v2.3.0 Streamable HTTP client source](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/src/mcp/client/streamable_http.py) |
