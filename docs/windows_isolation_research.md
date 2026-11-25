# STEWARD — C4-ISO Windows Isolation Research and Decision

**Batch:** C4-ISO — Windows isolation research and decision  
**Date:** 2026-11-25  
**Status:** Complete research; C4-I2 execution remains deferred  
**Binding review:** `docs/self_healing_review.md` §§4, 10.1, and 11  
**Decision:** **DEFER.** This host has no Windows Sandbox support, its Windows edition does not support the Hyper-V role, optional-feature state could not be queried without elevation, and no candidate boundary was constructed or proven. C4 remains **BACKLOG**.

This document answers review open questions 1 and 2. It adds no executor, sandbox, test, dependency, GUI behavior, command profile, or execution surface.

## 1. Scope, non-goals, and exact probe allowlist

### 1.1 Scope

This batch performed read-only host interrogation and mechanism research to decide whether C4-I2 can use an OS-enforced Windows isolation primitive on this machine. The governing question is not whether an API exists. It is whether a complete boundary can be shown to satisfy all 20 criteria in review §11 on the supported host.

The research also designs a hash-bound, data-only source/artifact transfer for a future boundary. That design is conditional on a later baseline selection and does not authorize execution now.

### 1.2 Non-goals

- No sandbox, VM, container, Job Object, AppContainer, firewall rule, ACL, registry value, user, token, process, or host configuration was created or changed.
- No repository, model, workspace, linter, test target, or arbitrary source code was executed.
- No child was spawned from repository content. The only helper was outside the repository and contained only the listed stdlib/`ctypes` queries.
- No product was selected by assertion of safety. A mechanism being capable of enforcing a property is not proof that this host enforces it for C4.
- No executor, transfer implementation, execution grant, or acceptance test is added.

### 1.3 Exact probe allowlist used

The following were the only platform probes used. API calls below are the exact calls in the external helper; the helper was run as `python 'C:\Users\WELCOME\AppData\Local\Temp\steward_c4_iso_probe.py'`. It was not committed.

1. Python stdlib:
   - `sys.getwindowsversion()`;
   - `platform.platform()`, `platform.version()`, `platform.machine()`, `platform.processor()`;
   - `winreg` **reads** under `HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion`, `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss`, and `HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\Packages`;
   - `importlib.util.find_spec()` for `win32api`, `win32job`, `win32security`, and `win32con` (specification lookup only; no pywin32 module was imported);
   - `ctypes.WinDLL` symbol lookup for the APIs listed in §2.7;
   - current-process token queries using `OpenProcessToken`, `GetTokenInformation` classes 20 (`TokenElevation`), 18 (`TokenElevationType`), 1 (`TokenUser`), and 3 (`TokenPrivileges`), plus `LookupPrivilegeValueW` and `ConvertSidToStringSidW`;
   - `IsProcessorFeaturePresent(20)` and `IsProcessorFeaturePresent(21)`.
2. Fixed OS queries:
   - `systeminfo`
   - `whoami /priv`
   - `DISM /Online /Get-FeatureInfo /FeatureName:Containers-DisposableClientVM`
   - `Get-WindowsOptionalFeature -Online | Select-Object FeatureName,State | Format-Table -AutoSize`
   - `netsh advfirewall show allprofiles`

No other platform query was used. In particular, this batch did not query `wsl.exe`, Docker, Hyper-V cmdlets, Windows Sandbox configuration, container images, or security products, because those probes were not in the allowed list.

## 2. HOST CAPABILITY FINDINGS — empirical

All excerpts in this section are from the probes above on 2026-11-25. Addresses are process-local and are evidence only that an export was resolvable in this process.

### 2.1 Windows edition and build

**API calls**

```python
sys.getwindowsversion()
platform.platform()
platform.version()
platform.machine()
platform.processor()
winreg.QueryValueEx(...)  # HKLM\SOFTWARE\Microsoft\Windows NT\CurrentVersion
```

**Verbatim output excerpt**

```text
sys.getwindowsversion(major=10, minor=0, build=26300, platform=2, service_pack='')
platform.platform() = 'Windows-11-10.0.26300-SP0'
platform.version() = '10.0.26300'
platform.machine() = 'AMD64'
platform.processor() = 'Intel64 Family 6 Model 141 Stepping 1, GenuineIntel'
ProductName = 'Windows 10 Home Single Language'
DisplayVersion = '26H2'
EditionID = 'CoreSingleLanguage'
InstallationType = 'Client'
CurrentBuild = '26300'
UBR = 10075
CurrentVersion = '6.3'
BuildLabEx = '26100.1.amd64fre.ge_release.240331-1435'
```

`systeminfo` independently reported:

```text
OS Name:                       Microsoft Windows 11 Home Single Language
OS Version:                    10.0.26300 N/A Build 26300
OS Configuration:              Standalone Workstation
System Type:                   x64-based PC
```

**What this establishes.** The machine is an x64 Windows client on build 26300 / display version 26H2. The registry `ProductName` retains the legacy “Windows 10” label, while `systeminfo`, `platform.platform()`, and `EditionID=CoreSingleLanguage` identify Windows 11 Home Single Language. The edition matters more than the legacy product-name string.

**What this does not establish.** It does not establish that any optional isolation feature is enabled or usable.

### 2.2 Virtualization and hypervisor state

**Command:** `systeminfo`

**Verbatim output excerpt**

```text
Total Physical Memory:         7,955 MB
Available Physical Memory:     885 MB
Virtual Memory: Max Size:      24,416 MB
Virtualization-based security: Status: Running
                               Available Security Properties:
                                     Base Virtualization Support
                                     Secure Boot
                                     DMA Protection
                                     UEFI Code Readonly
                                     SMM Security Mitigations 1.0
                                     Mode Based Execution Control
                                     APIC Virtualization
                               Services Configured:
                                     Hypervisor enforced Code Integrity
                               Services Running:
                                     Hypervisor enforced Code Integrity
                               App Control for Business policy: Enforced
                               App Control for Business user mode policy: Off
Hyper-V Requirements:          A hypervisor has been detected. Features required for Hyper-V will not be displayed.
```

**API calls**

```python
kernel32.IsProcessorFeaturePresent(20)  # PF_SECOND_LEVEL_ADDRESS_TRANSLATION
kernel32.IsProcessorFeaturePresent(21)  # PF_VIRTUAL_FIRMWARE_ENABLED
```

**Verbatim output**

```text
PF_SECOND_LEVEL_ADDRESS_TRANSLATION = False
PF_VIRTUAL_FIRMWARE_ENABLED = False
```

**What this establishes.** A hypervisor is active, VBS is running, and `APIC Virtualization` is reported available. The host is under an enforced App Control for Business policy. Only 885 MB physical memory was available at the initial probe; a later refresh of the same read-only command reported 568 MB available. Both are point-in-time observations.

**What this does not establish.** An active hypervisor does not establish that the Windows Hyper-V role, Hyper-V management tools, Windows Sandbox, or a usable VM can be installed or launched. The two processor-feature calls returned false while `systeminfo` reported an active hypervisor; these flags are not used to override the direct hypervisor observation. The available-memory reading is a point-in-time observation, not a capacity guarantee.

### 2.3 Windows Sandbox feature state

**Command:** `DISM /Online /Get-FeatureInfo /FeatureName:Containers-DisposableClientVM`

**Verbatim output**

```text
[Command exited with code 1]
Error: 740

Elevated permissions are required to run DISM.
Use an elevated command prompt to complete these tasks.
```

**Command:** `Get-WindowsOptionalFeature -Online | Select-Object FeatureName,State | Format-Table -AutoSize`

**Verbatim output**

```text
[Command exited with code 1]
Get-WindowsOptionalFeature : The requested operation requires elevation.
At line:1 char:1
+ Get-WindowsOptionalFeature -Online | Select-Object FeatureName,State ... ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
    + CategoryInfo          : NotSpecified: (:) [Get-WindowsOptionalFeature], COMException
    + FullyQualifiedErrorId : Microsoft.Dism.Commands.GetWindowsOptionalFeatureCommand
```

A narrowed `winreg` read of CBS package metadata found, among other package revisions:

```text
package = 'Containers-DisposableClientVM-Package~31bf3856ad364e35~amd64~~10.0.26100.10075' CurrentState = 64 Visibility = 2
package = 'Containers-DisposableClientVM-merged-Package~31bf3856ad364e35~amd64~~10.0.26100.1591' CurrentState = 64 Visibility = 2
```

**What this establishes.** The authoritative feature-state commands refused to run in this non-elevated session. CBS package metadata exists, but package `CurrentState`/`Visibility` values are not the same contract as DISM's enabled/disabled feature state.

**What this does not establish.** The enabled/disabled state of Windows Sandbox was **not determined**. Package metadata cannot substitute for the elevation-blocked feature query.

**Edition constraint.** Microsoft documents Windows Sandbox as included in Pro, Enterprise, Pro Education/SE, and Education, and explicitly says it is not supported on Windows Home. The observed edition is Home Single Language. Therefore this host is not an eligible Windows Sandbox baseline even though its feature query was blocked. Reference: [Windows Sandbox overview](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview).

### 2.4 Container and virtualization feature state

The same elevation-blocked commands prevented authoritative enumeration of Windows container, Hyper-V, Virtual Machine Platform, and WSL optional-feature states. The narrowed CBS read reported these representative package entries:

```text
package = 'Microsoft-Windows-Containers-OptionalFeatures-Package~31bf3856ad364e35~amd64~~10.0.26100.10075' CurrentState = 64 Visibility = 2
package = 'Microsoft-Hyper-V-Hypervisor-Package~31bf3856ad364e35~amd64~~10.0.26100.10075' CurrentState = 112 Visibility = 2
package = 'Microsoft-Windows-HyperV-OptionalFeature-VirtualMachinePlatform-Client-Package~31bf3856ad364e35~amd64~~10.0.26100.10075' CurrentState = 112 Visibility = 2
```

These values are package metadata, not feature-state proof.

**What this establishes.** CBS contains package revisions associated with containers, the Hyper-V hypervisor, and Virtual Machine Platform. The host has an active hypervisor.

**What this does not establish.** It does not establish that Windows containers can run, that Hyper-V management tools/VMs can be used, or that WSL2 is enabled. Exact feature state is **unknown** because the only authoritative commands refused elevation.

**Edition constraint.** Microsoft lists Hyper-V enablement on Windows client only for Windows 10/11 Professional or Enterprise, not Home. The observed `CoreSingleLanguage` edition therefore fails the supported-edition prerequisite for using the Hyper-V role as a baseline. Reference: [Hyper-V system requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/system-requirements-for-hyper-v-on-windows).

### 2.5 Hyper-V / WSL presence

**API call:** `winreg` read of `HKCU\Software\Microsoft\Windows\CurrentVersion\Lxss`.

**Verbatim output**

```text
distribution_count = 1
distribution['{8a73c331-f5db-43b8-b3d9-bfb3e211cca9}'] = {'DistributionName': 'docker-desktop', 'Version': 2, 'State': 1, 'DefaultUid': 0}
```

Combined with `systeminfo`'s active-hypervisor output, this establishes that WSL registration metadata exists for a `docker-desktop` distribution and that a hypervisor is active.

It does **not** establish a general-purpose, project-owned WSL distribution, WSL2 feature state, WSL networking posture, interop posture, or that Docker is operational. This batch did not execute `wsl.exe` or Docker.

### 2.6 Elevation and token privileges

**Command:** `whoami /priv`

**Verbatim output**

```text
PRIVILEGES INFORMATION
----------------------

Privilege Name                Description                          State
============================= ==================================== ========
SeShutdownPrivilege           Shut down the system                 Disabled
SeChangeNotifyPrivilege       Bypass traverse checking             Enabled
SeUndockPrivilege             Remove computer from docking station Disabled
SeIncreaseWorkingSetPrivilege Increase a process working set       Disabled
SeTimeZonePrivilege           Change the time zone                 Disabled
```

**API calls**

```python
OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, ...)
GetTokenInformation(token, TokenElevation, ...)
GetTokenInformation(token, TokenElevationType, ...)
GetTokenInformation(token, TokenUser, ...)
GetTokenInformation(token, TokenPrivileges, ...)
```

**Verbatim output excerpt**

```text
TokenIsElevated = False
TokenElevationType = 3 'Limited'
TokenUser SID = 'S-1-5-21-3640953120-1726909942-1407588585-1001'
assigned_privilege_count = 5
privilege[0] = 'SeShutdownPrivilege' LUID=(19,0) attributes=0x00000000 []
privilege[1] = 'SeChangeNotifyPrivilege' LUID=(23,0) attributes=0x00000003 ['SE_PRIVILEGE_ENABLED_BY_DEFAULT', 'SE_PRIVILEGE_ENABLED']
privilege[2] = 'SeUndockPrivilege' LUID=(25,0) attributes=0x00000000 []
privilege[3] = '<unmapped>' LUID=(33,0) attributes=0x00000000 []
privilege[4] = '<unmapped>' LUID=(34,0) attributes=0x00000000 []
```

**What this establishes.** The session is non-elevated with a limited token. Only `SeChangeNotifyPrivilege` is enabled. The available token does not include enabled `SeDebugPrivilege`, `SeTcbPrivilege`, `SeAssignPrimaryTokenPrivilege`, `SeImpersonatePrivilege`, `SeBackupPrivilege`, or `SeRestorePrivilege`. The absence of those enabled privileges is compatible with creating a restricted token but does not prove that token creation, impersonation, AppContainer activation, ACL changes, or firewall administration can be performed by this session.

### 2.7 `ctypes` and pywin32 paths

**API calls:** `ctypes.WinDLL(...).<symbol>` for relevant Job Object, restricted-token, and AppContainer exports.

**Verbatim output excerpt**

```text
kernel32.dll!CreateJobObjectW = 0x7ffd37e8c5e0
kernel32.dll!AssignProcessToJobObject = 0x7ffd37e8eef0
kernel32.dll!SetInformationJobObject = 0x7ffd37e87db0
kernel32.dll!TerminateJobObject = 0x7ffd37e90ea0
kernel32.dll!IsProcessInJob = 0x7ffd37e8f930
advapi32.dll!CreateRestrictedToken = 0x7ffd38535eb0
advapi32.dll!SetTokenInformation = 0x7ffd38534290
advapi32.dll!AdjustTokenPrivileges = 0x7ffd38531f50
userenv.dll!CreateAppContainerProfile = 0x7ffd34eb7fe0
userenv.dll!DeriveAppContainerSidFromAppContainerName = 0x7ffd34eb7b60
userenv.dll!DeleteAppContainerProfile = 0x7ffd34eb90f0
```

**API call:** `importlib.util.find_spec(module_name)` for pywin32 modules.

**Verbatim output**

```text
win32api = None
win32job = None
win32security = None
win32con = None
```

**What this establishes.** The relevant native entry points are exported and reachable through stdlib `ctypes`; no third-party wrapper is needed merely to address those APIs. The pywin32 modules are not installed. Export presence says nothing about policy permission, successful object creation, isolation behavior, or sufficiency as a complete sandbox.

### 2.8 Firewall policy state

**Command:** `netsh advfirewall show allprofiles`

**Verbatim output excerpt** (identical for all three profiles)

```text
State                                 ON
Firewall Policy                       BlockInbound,AllowOutbound
LocalFirewallRules                    N/A (GPO-store only)
LocalConSecRules                      N/A (GPO-store only)
InboundUserNotification               Enable
RemoteManagement                      Disable
UnicastResponseToMulticast            Enable
```

**What this establishes.** Windows Firewall is enabled for Domain, Private, and Public profiles, with inbound blocked and outbound allowed. Policy/rules are GPO-store oriented.

**What this does not establish.** The observed default does not deny egress. No C4-specific rule exists or was added. This probe cannot prove denial of DNS, direct IP, proxy, loopback, or side channels. A child-specific default-deny policy would still require a separate reviewed implementation and proof.

### 2.9 Consolidated host capability table

| Capability | Empirical finding | Confidence / gap |
|---|---|---|
| OS | Windows 11 Home Single Language, x64, build 26300, 26H2 | Observed |
| Active hypervisor / VBS | Hypervisor detected; VBS running; APIC virtualization available | Observed |
| Windows Sandbox feature | Authoritative state query refused elevation | **Unknown** |
| Windows Sandbox eligibility | Not supported on Windows Home | Excluded by edition |
| Container feature | Authoritative state query refused elevation | **Unknown** |
| Hyper-V role | Authoritative state query refused elevation; Home edition not supported for role | **Excluded as baseline** |
| WSL presence | `docker-desktop` Lxss registration, version 2; active hypervisor | Observed registration only; runtime posture unknown |
| Elevation | Non-elevated, limited token | Observed |
| Relevant privileges | Only `SeChangeNotifyPrivilege` enabled | Observed |
| Firewall | All profiles on; inbound block/outbound allow | Observed; not default-deny egress |
| Job/restricted-token/AppContainer APIs | Relevant exports resolvable via `ctypes` | Observed availability only |
| pywin32 | Not installed | Observed |
| App Control for Business | Policy enforced | Observed; compatibility unknown |

## 3. Candidate mechanism analysis

No candidate below was constructed or enabled. “Works” describes the documented mechanism, not observed behavior on this host.

### 3.1 Candidate A — Windows Sandbox (disposable VM)

Microsoft describes Windows Sandbox as a disposable, pristine, hypervisor-isolated desktop. It uses a separate guest kernel, host-installed software is unavailable, closing it discards state, and networking is enabled by default but can be disabled in configuration. Microsoft recommends running untrusted applications with networking disabled and a read-only mapped folder.

- **Isolation mechanism:** strongest candidate in principle because the hostile workload receives a separate kernel; a disposable guest also removes ordinary host-state persistence.
- **What it can enforce:** guest filesystem/registry isolation, disabled networking, process lifetime bounded by guest/session lifetime, fresh state per launch, and a bounded mapped input surface.
- **What it does not automatically enforce:** exact CPU/memory/handle/process/scratch caps; host-side observation caps; grant replay protection; authenticated artifact transport; or C3 non-bypass. These remain C4-I2 responsibilities and focused-test obligations.
- **Availability prerequisite:** supported Windows edition, optional feature enabled, virtualization, and sufficient host capacity.
- **Host result:** **excluded**. Microsoft explicitly says Windows Sandbox is not supported on Home; this host is Home Single Language. The blocked feature query is recorded as unknown, not converted into an enabled/disabled claim.
- **Startup/operating cost:** low-to-moderate launch footprint versus a full VM, but multiple simultaneous instances are not supported; available physical memory was only 568–885 MB across read-only observations during this research.
- **Transfer fit:** a read-only host input mapping and a separate data-only output mapping are plausible, but the returned-artifact authentication mechanism must be implemented and proven as described in §5.

Reference: [Windows Sandbox overview](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview).

### 3.2 Candidate B — Hyper-V virtual machine

A dedicated Windows guest under the Hyper-V role provides a separate kernel and explicit guest lifecycle, disk, configuration, and network controls. It can meet the isolation principle more completely than an in-process/token sandbox if the guest is purpose-built and the host never exposes a general control channel to it.

- **Isolation mechanism:** hypervisor-enforced guest kernel; guest filesystem/network are distinct from host state.
- **What it can enforce:** denied host filesystem/registry access, isolated guest networking, guest-local scratch, explicit VM lifecycle, and guest-side process/resource controls.
- **What it does not automatically enforce:** source/artifact authentication, C4 grant semantics, exact resource margins, bounded host pipes, or C3 integration.
- **Availability prerequisite:** Windows client Pro/Enterprise for the Hyper-V role per Microsoft, supported CPU/BIOS/DEP/SLAT, role/management tools, a provisioned guest image, and host capacity.
- **Host result:** **excluded as the supported baseline**. The role’s authoritative feature state could not be queried without elevation, and—decisively—the observed Home Single Language edition is outside Microsoft’s listed client editions for enabling Hyper-V. The active hypervisor/VBS state does not change that edition gate.
- **Startup/operating cost:** materially higher than a token/process boundary: image lifecycle, updates, guest maintenance, networking, and host memory/disk reservation.
- **Transfer fit:** a one-way/read-only input medium and a separately collected output medium can avoid a host command channel, but the chosen transport and artifact authentication are implementation work, not inherent Hyper-V guarantees.

Reference: [Hyper-V system requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/system-requirements-for-hyper-v-on-windows).

### 3.3 Candidate C — WSL2 / Linux VM boundary

WSL2 uses a Linux virtual machine and therefore provides stronger separation than a Windows process sandbox. The observed host has one WSL registration (`docker-desktop`) and an active hypervisor.

- **Isolation mechanism:** Linux guest kernel and filesystem, distinct from Windows.
- **What it can enforce:** Linux-side filesystem/process/network isolation and disposable distro behavior when configured appropriately.
- **What it does not automatically enforce:** Windows executable isolation, Windows AppData/registry isolation, absence of Windows interop, host-mount denial, default-deny networking, or faithful execution of Windows-only linters/tests. WSL's default NAT network and mirrored-mode host reachability are material risks unless configured and tested.
- **Availability prerequisite:** WSL2 and a project-owned distro, controlled mounts/interop, networking policy, and a command/runtime compatible with the Linux guest.
- **Host result:** **not selected**. Only a Docker-managed distro registration was observed; the project has no approved Linux execution profile, and WSL interop/mount/network posture was not probed. The `docker-desktop` distro is not an owned baseline.
- **Startup/operating cost:** moderate; a dedicated immutable or reproducible distro plus mount/interop policy is required.
- **Transfer fit:** a Linux guest can use a read-only input mount and data-only output directory, but accepting it would change the execution environment and therefore the dependency/interpreter identity under review criteria 4–6.

Reference: [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking).

### 3.4 Candidate D — Windows containers

Windows containers share the host kernel in process-isolation mode; Hyper-V-isolated containers add a utility VM boundary. Their image/filesystem model, restricted host integration, per-container resource controls, and namespace-like isolation can provide useful defense in depth, but they are not equivalent to a disposable desktop VM and their Windows edition/image requirements are stricter than “a container runtime exists.”

- **Isolation mechanism:** process isolation gives separate container identity, filesystem namespace, registry view, and selected kernel objects on a shared kernel; Hyper-V isolation adds a utility VM.
- **What it can enforce:** restricted host filesystem/registry access, container-local scratch, network isolation through Windows Container Networking/firewall rules, and CPU/memory/process/handle controls through host/container policies.
- **What it does not automatically enforce:** disposable state, no host-mount escape, a trusted image/dependency chain, artifact authenticity, grant/C3 semantics, or a hard denial of every side channel.
- **Availability prerequisite:** a supported client edition and feature set, compatible container engine and Windows base image, networking/HostProcess/VPN compatibility, and verified runtime behavior.
- **Host result:** **unknown/unavailable for selection**. The authoritative feature query was elevation-blocked. The only WSL registration is `docker-desktop`; no Windows container image/runtime posture was probed, and CBS package metadata cannot establish a usable container stack.
- **Startup/operating cost:** moderate for a prebuilt image, but image lifecycle and Windows-container host compatibility add operational burden.
- **Transfer fit:** build/read-only source layers and an extracted artifact volume are plausible; a content-addressed manifest can avoid a general host command channel. Exact image and network policy remain unselected.

### 3.5 Candidate E — Job Object + restricted token + ACL + firewall composite

This candidate combines several host-local controls: a Job Object owns and bounds the descendant tree; a restricted token removes privileges and applies restricted SIDs; explicit ACLs deny access to authoritative workspace, AppData, user profile, and unrelated roots; Windows Firewall application rules deny egress; the controller bounds wall clock and captures.

- **Isolation mechanism:** enforcement in the same Windows kernel and host filesystem. It is a policy/least-privilege boundary, not a kernel boundary.
- **What it can enforce:** process-tree association/termination (provided breakaway is denied), CPU/memory/process/handle limits, token privilege removal, filesystem denial through ACLs, and per-application outbound blocking.
- **What it does not automatically enforce:** protection from a kernel/OS escape, same-integrity exploitation of shared services, writable/readable host paths granted by ACL mistakes, reparse/path races outside cooperative code, complete DNS/direct-IP/proxy/loopback denial without a verified firewall configuration, scratch/output caps for every artifact route, or cryptographic authentication of returned files.
- **Availability prerequisite:** an explicitly designed launch sequence (normally suspended child → restricted token → Job assignment → resume), correct ACL construction, firewall administration/policy, and reliable process-tree/side-channel tests.
- **Host result:** **not selected**. Relevant exports are present through `ctypes`; the session is non-elevated with a limited token; local firewall rules are GPO-store oriented and outbound is allowed. No Job, token, ACL, or firewall rule was created, so this candidate is not proven. The same-kernel model also makes it less defensible than a VM for hostile code.
- **Startup/operating cost:** low to moderate, but with the largest proof surface and highest sensitivity to Windows version, policy, token, ACL, and firewall details.
- **Transfer fit:** a host-created source bundle and a restricted ACL-protected scratch/output directory can be hash-bound, but because this boundary shares the host kernel, it is the weakest candidate against an explicit kernel-escape threat model.

Reference: [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects) and [Windows Firewall rules](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules).

### 3.6 Candidate F — AppContainer capability boundary

AppContainer gives an application a combined user/application identity, least-privilege file/registry access, and granular network capabilities. It is useful for untrusted applications and naturally limits unneeded device/network resources.

- **Isolation mechanism:** restricted token plus capability SIDs and AppContainer-specific file/registry/network enforcement in the shared Windows kernel.
- **What it can enforce:** denial of ungranted filesystem/registry resources, no Internet capability by default, no user credential impersonation, and per-app network/device restrictions.
- **What it does not automatically enforce:** process-tree resource caps, wall clock, scratch/output accounting, explicit Job Object termination, all kernel side channels, or exact host-root denial without an explicit ACL design. Creating a profile is state-changing and may require permissions; the export probe proves none of that behavior.
- **Availability prerequisite:** an AppContainer profile/capability design, a launch path that actually enters the AppContainer token, compatible executable/package identity, explicit denied roots, network capability policy, and a Job/resource layer.
- **Host result:** **not selected**. Relevant `userenv.dll` exports are resolvable, but the session is non-elevated and no profile, token, capability, process, or filesystem behavior was created or tested. AppContainer alone cannot satisfy resource and process-tree criteria; it would need the composite controls of Candidate E.
- **Startup/operating cost:** low after profile preparation; preparation and compatibility are nontrivial.
- **Transfer fit:** an ACL/capability-scoped source bundle and output directory are feasible; exact hash authentication and refusal behavior are still C4-I2 work.

Reference: [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation).

### 3.7 Candidate G — third-party sandboxing

A third-party product could supply a maintained Windows sandbox, driver, or orchestration layer and might support Home editions. No such product is installed, approved, dependency-audited, or probed in this batch.

- **Potential advantage:** packaging and support for isolation mechanics that are costly to implement directly.
- **Trust cost:** the product becomes part of the execution root of trust. Its driver/service, update channel, image contents, IPC, telemetry, crash dumps, and licensing/admin behavior all affect the boundary.
- **Host result:** **unknown**. No product is proposed or selected because the review explicitly requires a dependency-audited, pinned isolation identity, and this batch may not install or evaluate one.
- **Operating cost:** vendor/runtime lifecycle and an additional privileged trust surface.
- **Transfer fit:** product-specific and therefore not yet designable.

### 3.8 Candidate H — no OS-enforced boundary / Python-only execution

Fixed argv, environment scrubbing, deadlines, bounded pipes, and journals can constrain accidental behavior but cannot contain hostile code in the host kernel.

- **Host result:** this is the current state and is explicitly rejected by the binding review.
- **Decision effect:** it is a refusal/fallback posture, not a baseline. C4 execution must not proceed under it.

## 4. CAPABILITY MATRIX — all 20 review §11 criteria

Status meanings are defined in §4.1. “Provable” is a mechanism assessment, not a claim that C4-I2 has passed on this host. Candidate labels are A–H as defined in §3.

### 4.1 Status legend

- **Provable:** the candidate can satisfy the criterion when correctly integrated and focused tests pass.
- **Partially provable:** the candidate supplies part of the needed enforcement; another control or unresolved condition is required.
- **Not provable:** the candidate cannot satisfy the criterion.
- **Unknown:** candidate availability/behavior or the future implementation prevents an evidence-backed assessment.

A controller-level “Provable” means the C4-I1 controller or an ordinary C4-I2 application control can satisfy that part; it does not imply that the isolation candidate itself is available on this host.

### 4.2 Criteria 1–5

| Candidate | 1. Isolation proof | 2. Process-tree proof | 3. Resource proof | 4. Fixed command proof | 5. No shell |
|---|---|---|---|---|---|
| A. Windows Sandbox | **Provable** — separate guest kernel; networking off and read-only input can be configured | **Provable** — guest/session disposal plus guest supervisor | **Partially provable** — VM/guest supervisor and volumes needed for exact handle/process/scratch/output caps | **Provable** — C4 fixed profile independent of boundary | **Provable** — C4 direct argv launch |
| B. Hyper-V VM | **Provable** — separate guest kernel and guest resources | **Provable** — stop/terminate guest and reap guest processes | **Partially provable** — guest supervisor/volumes needed for all caps | **Provable** — C4 fixed profile | **Provable** — C4 direct argv launch |
| C. WSL2/Linux guest | **Partially provable** — Linux kernel helps, but WSL mounts/interop/host reachability must be closed | **Partially provable** — distro termination is strong but WSL-specific late descendants/interop need proof | **Partially provable** — distro/VM settings needed for exact caps | **Partially provable** — Linux profile/interpreter identity must be approved | **Provable** — direct argv within approved profile |
| D. Windows containers | **Partially provable** — namespace-like isolation; process mode shares kernel, utility-VM mode stronger | **Partially provable** — container/job termination must cover late descendants | **Partially provable** — engine policies/volumes must enforce every cap | **Provable** — C4 fixed profile | **Provable** — C4 direct argv launch |
| E. Job+token+ACL+firewall | **Partially provable** — same kernel; least privilege and ACL/firewall controls only | **Provable** — closed Job with breakaway denied can own descendants | **Partially provable** — Job covers many resources but scratch/output need volume/controller enforcement | **Provable** — C4 fixed profile | **Provable** — C4 direct argv launch |
| F. AppContainer | **Partially provable** — capability isolation in shared kernel; explicit ACL/network policy required | **Partially provable** — token restricts children but does not itself reap/kill a tree | **Not provable** — no wall-clock/process/handle/scratch enforcement alone | **Provable** — C4 fixed profile | **Provable** — C4 direct argv launch |
| G. Third-party sandbox | **Unknown** — no approved/probed product | **Unknown** — product behavior unknown | **Unknown** — product controls unknown | **Provable** — C4 can still pin argv, but product launch API must conform | **Provable** — C4 direct argv launch |
| H. Python-only | **Not provable** — no OS-enforced kernel/filesystem/network boundary | **Not provable** — cooperative termination only | **Partially provable** — controller bounds time/output; OS resources remain unbounded | **Provable** — C4 fixed profile | **Provable** — C4 direct argv launch |

### 4.3 Criteria 6–10

| Candidate | 6. Absolute executable/environment | 7. Separate execution grant | 8. C3 mandatory | 9. No-auto-apply | 10. Hard iteration bound |
|---|---|---|---|---|---|
| A. Windows Sandbox | **Provable** — pin guest image, executable, interpreter, env, cwd | **Provable** — C4 single-use expiring grant | **Provable** — existing C3 exact-diff path | **Provable** — C4-I1 non-apply proof plus C4-I2 spy | **Provable** — C4-I1 focused/mutation proof |
| B. Hyper-V VM | **Provable** — pin guest image, executable, interpreter, env, cwd | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| C. WSL2/Linux guest | **Partially provable** — pin Linux image/interpreter/env; current-directory import/interop denied | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| D. Windows containers | **Provable** — pin image, executable, interpreter, env, cwd | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| E. Job+token+ACL+firewall | **Provable** — pin executable/interpreter/env/cwd; restricted token | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| F. AppContainer | **Provable** — pin package/executable/interpreter/env/cwd and capabilities | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| G. Third-party sandbox | **Unknown** — product IPC could alter launch identity | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4 spy proof | **Provable** — C4-I1 proof |
| H. Python-only | **Provable** — C4 can scrub/pin argv/env, but does not contain the executable | **Provable** — C4 grant | **Provable** — existing C3 path | **Provable** — C4-I1 proof; unsafe execution still refused | **Provable** — C4-I1 proof |

### 4.4 Criteria 11–15

| Candidate | 11. Controller time/output bounds | 12. Termination semantics | 13. Write-ahead ordering | 14. Crash recovery | 15. Bounded observation |
|---|---|---|---|---|---|
| A. Windows Sandbox | **Provable** — C4-I1 controller owns count/time/output bounds | **Provable** — typed C4 states plus boundary disposal | **Provable** — C4-I1 write-ahead pattern | **Provable** — uncertain intent; kill guest before reconciliation | **Provable** — C4-I1 bounded/redacted observation |
| B. Hyper-V VM | **Provable** — C4-I1 controller | **Provable** — typed C4 states plus VM stop | **Provable** — C4-I1 pattern | **Provable** — uncertain intent; stop VM before reconciliation | **Provable** — C4-I1 bounds |
| C. WSL2/Linux guest | **Provable** — C4-I1 controller | **Provable** — typed states plus distro termination | **Provable** — C4-I1 pattern | **Partially provable** — distro termination/reconciliation must be proven | **Provable** — C4-I1 bounds |
| D. Windows containers | **Provable** — C4-I1 controller | **Provable** — typed states plus container stop | **Provable** — C4-I1 pattern | **Partially provable** — container/job cleanup/reconciliation must be proven | **Provable** — C4-I1 bounds |
| E. Job+token+ACL+firewall | **Provable** — C4-I1 controller | **Provable** — typed states plus Job termination | **Provable** — C4-I1 pattern | **Provable** — closed Job kill-on-close; uncertain until tree known stopped | **Provable** — C4-I1 bounds |
| F. AppContainer | **Provable** — C4-I1 controller | **Partially provable** — capability isolation does not kill/reap tree | **Provable** — C4-I1 pattern | **Not provable** — without Job/explicit tree owner, survivors cannot be proven stopped | **Provable** — C4-I1 bounds |
| G. Third-party sandbox | **Provable** — C4-I1 controller | **Unknown** — depends on product lifecycle API | **Provable** — C4-I1 pattern | **Unknown** — product reconciliation semantics unknown | **Provable** — C4-I1 bounds |
| H. Python-only | **Provable** — C4-I1 controller | **Partially provable** — typed states but descendant cleanup is cooperative | **Provable** — C4-I1 pattern | **Not provable** — surviving hostile tree cannot be proven stopped | **Provable** — C4-I1 bounds |

### 4.5 Criteria 16–20

| Candidate | 16. Secret hygiene | 17. Journal privacy/durability | 18. No stale-loop behavior | 19. Hostile repository proof | 20. Full regression proof |
|---|---|---|---|---|---|
| A. Windows Sandbox | **Provable** — minimal guest env plus C4 redaction; no provider keys | **Provable** — C4-I1 bounded durable journal | **Provable** — C4 grant/epoch checks | **Provable in principle** — guest kernel plus read-only source; exact tests required | **Unknown** — future C4-I2 tests do not exist |
| B. Hyper-V VM | **Provable** — minimal guest env plus C4 redaction | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Provable in principle** — guest kernel plus controlled media; exact tests required | **Unknown** — future tests do not exist |
| C. WSL2/Linux guest | **Provable** — minimal Linux env plus C4 redaction | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Partially provable** — WSL mounts/interop/reparse behavior needs focused proof | **Unknown** — future tests do not exist |
| D. Windows containers | **Provable** — minimal container env plus C4 redaction | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Partially provable** — image/mount/runtime behavior needs focused proof | **Unknown** — future tests do not exist |
| E. Job+token+ACL+firewall | **Provable** — restricted env/token plus C4 redaction | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Partially provable** — same-kernel/ACL/reparse/firewall attack surface needs focused proof | **Unknown** — future tests do not exist |
| F. AppContainer | **Provable** — capability-scoped identity plus C4 redaction | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Partially provable** — capabilities/ACLs and missing tree/resource controls need proof | **Unknown** — future tests do not exist |
| G. Third-party sandbox | **Unknown** — product IPC/crash dumps may leak secrets | **Provable** — C4 journal, but product stores excluded | **Provable** — C4 grant/epoch checks | **Unknown** — no product behavior evidence | **Unknown** — future tests do not exist |
| H. Python-only | **Partially provable** — env scrub/redaction helps but host code can still be attacked | **Provable** — C4-I1 journal | **Provable** — C4 grant/epoch checks | **Not provable** — no boundary to escape from | **Unknown** — future tests do not exist |

### 4.6 Matrix conclusion

No candidate is marked “already proven” on this host because no candidate boundary was constructed. A and B are the only candidates whose isolation principle can plausibly cover the full hostile-code threat model across kernel, filesystem, and network, but both are unavailable on the observed Home edition for their documented Windows roles. D may be strong enough with utility-VM isolation but its feature/runtime/image posture is unknown. E/F are same-kernel composites and require materially more proof. G is an unapproved dependency. H fails the binding isolation requirement.

## 5. Hash-bound source/artifact transfer design (conditional)

This section answers review open question 2. It is a protocol design for a future implementation, not an implemented transport.

### 5.1 Required properties

The transfer must not create a general host command channel. Specifically:

1. The host may provision a **single immutable input bundle** before launch and read a **single bounded output collection** after boundary shutdown. It must not expose a shell, RPC endpoint, host-mounted writable workspace, or reusable command queue.
2. The source manifest must bind run ID, grant ID, command-profile ID, source/workspace fingerprint, epoch, isolation identity, normalized relative paths, byte lengths, file kinds, and SHA-256 hashes to one canonical manifest root.
3. The boundary must verify the source manifest and every admitted byte before the hostile workload starts. A mismatch is refusal, not a retry with different bytes.
4. The return protocol must bind the same run/grant/source-manifest-root tuple to a canonical artifact manifest containing normalized relative paths, byte lengths, and SHA-256 hashes. The host must independently hash received bytes and recompute the artifact-manifest root.
5. “Hashes match” proves byte identity, not that a benign process produced the bytes or that the guest is trustworthy. Returned artifacts remain **untrusted data** and can reach C3 only as bounded proposal material.

### 5.2 Inbound source path

- The host admission component creates a new disposable directory, opens each admitted source with no-follow/reparse-safe semantics, copies bytes into a fresh file, and computes SHA-256 while copying.
- It rejects absolute paths, `..`, alternate data streams, device/reparse paths, unsupported file kinds, duplicate normalized paths, files outside the admitted source set, and anything beyond reviewed count/byte limits.
- It creates a canonical, length-delimited manifest and computes a manifest root. The root is bound into the single-use execution grant.
- The bundle and manifest are placed in a read-only input medium/mapping. The authoritative workspace and AppData are never mapped into the boundary.
- A trusted boundary runner verifies the manifest with a pinned verifier, verifies the grant binding, materializes only an isolated copy, and then starts the fixed command. Hostile code cannot select a different bundle through the transfer channel.

### 5.3 Outbound artifact path

- A trusted boundary broker—not the hostile workload—enumerates a fixed output allowlist, rejects links/reparse points and out-of-root paths, computes SHA-256 per artifact, and creates a canonical artifact manifest bound to the input manifest root.
- The broker signs that manifest with a per-boundary identity whose public key is pinned to the approved isolation identity. For a VM/container baseline this should use a platform-attested, non-exportable boundary/broker key; for Windows Sandbox or a host-local composite, the design must find an equivalent protected signer. If no such signer can be protected from the hostile child, the baseline cannot satisfy the authentication requirement.
- The host verifies the signer identity, signature, grant/run binding, manifest root, path allowlist, count/byte caps, and independently recomputed hashes before admitting any artifact to the proposal pipeline.
- The host does not execute, import, open as code, or auto-apply returned artifacts. The bounded artifact bytes and exact diff still require the existing single-use C3 human approval.

### 5.4 Failure/refusal behavior

The following are hard refusals: unknown or stale isolation identity; missing/expired/replayed/wrong-scope grant; input manifest signature/root/hash mismatch; unapproved source path or file kind; output signer unknown or signature invalid; source/return run tuples differ; extra, missing, linked, or out-of-allowlist artifact; count/byte/scratch cap exceeded; independently recomputed artifact hash/root mismatch; malformed manifest; or transport/storage failure.

On refusal, the boundary is stopped or discarded, the output is quarantined or deleted without becoming proposal input, no C3 request is made, no patch path is reachable, and the journal records a typed refusal/failure. There is no retry under a different profile, a weakened hash rule, an unsigned channel, or a host command channel.

### 5.5 Current feasibility

A VM/container with an attested guest broker can plausibly implement this protocol. Windows Sandbox may support the input mapping and guest lifecycle, but this batch did not establish a protected signer/attestation path; its documented network default also requires an explicit disabled-network configuration. Host-local Job/token/AppContainer designs cannot claim boundary provenance merely from same-host hashes and are especially dependent on a broker that the hostile child cannot impersonate.

Because the binding baseline is deferred, this protocol is a **required design constraint**, not evidence that a compliant transfer exists on the current host.

## 6. DEPENDENCY DECISION

### 6.1 Decision

**No new Python or third-party dependency is approved by C4-ISO.** A future C4-I2 implementation should prefer the Python standard library and narrow OS-native adapters. pywin32 and an unapproved third-party sandbox are not selected.

### 6.2 Rationale and precedent

- **Standard library first:** `ctypes` can address the observed Job Object, restricted-token, and AppContainer exports without adding a package. The same-kernel APIs are available on the host, although no boundary was created. `hashlib`, `hmac`, `json`, `pathlib`, and existing process/pipe facilities cover hashing and canonical metadata without a crypto package.
- **pywin32 rejected for now:** it is not installed. Adding it would create dependency and update-trust obligations for wrappers around APIs that `ctypes` can call. If a future implementation proves that pywin32 materially reduces error-prone API marshaling, it requires a separate dependency review and pinned version/hash; C4-ISO does not approve it.
- **External sandbox rejected:** an unprobed vendor sandbox adds a driver/service/image/IPC root of trust. No product met the dependency-audit bar.
- **Existing precedent — FS-S5:** `PLAN.md` lines 152–175 records that third-party locking packages were rejected as an unnecessary dependency because OS-managed locking was sufficient. C4-ISO applies the same “prefer OS/std lib, avoid unreviewed dependency” rule.
- **Existing precedent — C3-R:** `PLAN.md` lines 318–328 records the reviewed choice of formatting-preserving **stdlib AST/token splicing** rather than an unapproved parser stack. C4-ISO likewise prefers a pinned standard-library/native path over convenience dependencies.

### 6.3 Boundary-specific implication

- If A/B/D (VM/container) is later selected, the OS-native lifecycle and its image/runtime become explicit pinned dependencies and require their own audit; the control adapter itself should remain stdlib-only.
- If E/F is selected, `ctypes` is acceptable for a narrow Win32 adapter, but every structure, handle lifetime, token/ACL/firewall operation, and error path needs focused tests and mutation proof.
- If G is selected, that product is not “just tooling”: it becomes part of the execution root of trust and requires version, hash, update, service/driver, image, and IPC review before use.

## 7. C4-I2 test strategy and proof obligations

No strategy in this section was run in C4-ISO because no executor or boundary exists. It defines the proof that a future supported baseline must produce.

### 7.1 Criterion-by-criterion proof plan

| §11 criterion | Concrete future proof | Pass condition |
|---|---|---|
| 1. Isolation proof | In an isolated disposable copy, attempt writes to authoritative workspace, AppData, user profile, unrelated roots, mapped-host paths, device/reparse targets, DNS, direct IPv4/IPv6, proxy, and loopback from multiple child identities and late descendants | Every attempt is denied by the named OS control; host canaries unchanged |
| 2. Process-tree proof | Child spawns direct, nested, delayed, orphaned, breakaway-attempting, and same-process descendants; cancel/timeout at each phase | All descendants are killed/reaped; no surviving PID/job membership after boundary close |
| 3. Resource proof | Burn CPU, allocate memory/open handles, fork beyond count, fill scratch/output, and emit oversized streams | Every external cap trips at the configured value before host margin is consumed; violation is bounded failure |
| 4. Fixed command proof | Inject model/user values into every parameter class; mutate profile/executable/interpreter/env/cwd/target | Constructed argv/profile is byte-for-byte the approved value or execution is refused |
| 5. No shell | Use shell metacharacters, spaces, quotes, substitutions, and metacharacter-only filenames | They remain argv bytes; no shell process is created |
| 6. Absolute executable/environment proof | Inspect actual child token/env/cwd/PYTHONPATH/PATH; substitute executable bytes or alter image/profile | Identity is pinned/verified and no forbidden secret/import/path value is present |
| 7. Separate execution grant | Exercise missing, stale, replayed, expired, changed target/source/workspace/epoch/profile/limit/isolation values | Every invalid case launches zero processes and records a typed refusal |
| 8. C3 mandatory | Route a bounded child artifact into proposal/approval with spies on C3 | Only the exact diff reaches the existing single-use C3 gate; no alternate apply path exists |
| 9. No-auto-apply | Fake C4 applier raises if reached; hostile output attempts to name/apply a patch | Fake applier is never called |
| 10. Hard iteration bound | Existing mutation from C4-I1 plus fake always-failing executor | Exactly configured maximum calls; weakened count check turns test RED and restoration GREEN |
| 11. Controller-owned bounds | Return hostile count/time/output/excerpt values and attempt extension | Controller values remain authoritative and total/per-iteration caps hold |
| 12. Termination semantics | Inject one cause per required terminal state, including journal/authorization failures | Each maps deterministically to the specified state and durable record |
| 13. Write-ahead ordering | Fail intent write before launch; fail outcome write after launch | Intent failure causes zero launches; outcome failure is `uncertain`, never success |
| 14. Crash recovery | Interrupt controller/executor with live descendants and reload journal | State is `uncertain`; no auto-retry until tree known stopped and human reconciliation occurs |
| 15. Bounded observation | Emit binary/oversized/multibyte stdout/stderr beyond each cap | Deterministic bounded excerpt and counts; no unbounded bytes in journal/UI/provider |
| 16. Secret hygiene | Seed canary environment/API-key/header/private-key forms and inspect every sink | Child lacks avoidable secrets; sinks contain deterministic markers/counts and no canary |
| 17. Journal privacy/durability | Concurrent writers, forced write/replace failure, privacy inspection | Durable ordered bounded records; no source/unbounded output; cross-process serialization holds |
| 18. No stale-loop behavior | Change run/plan/workspace/epoch and cancel at every safe boundary | Grants invalidate and loop stops truthfully with deterministic state |
| 19. Hostile repository proof | Seed malicious source/test/plugin, hostile filenames, symlink/junction/reparse targets, environment, argv, and output | No escape, no command influence, no unapproved path/write |
| 20. Full regression proof | Run dedicated RED→GREEN/mutation tests plus existing discovery/validator/compile/diff gates on the supported host | All required gates green; production AppData/real source untouched; only known symlink skip |

### 7.2 Required test isolation

Tests that attempt hostile behavior must themselves run inside the future disposable boundary and use temporary canaries. Tests must not use real STEWARD source, production AppData, provider keys, or `steward.db`/`secret.key`. The review’s repository rule remains: never write, delete, or recreate those protected files; a changed hash during normal use is not a defect.

### 7.3 Host qualification gate

Before any C4-I2 run, record:

- exact OS edition, build, and feature-state output;
- exact isolation provider/image/runtime identity and version/hash;
- virtualization and capacity status;
- firewall/network configuration;
- App Control/antivirus/enterprise-policy constraints;
- dependency/interpreter/linter identity;
- expected host margins and refusal thresholds.

A missing or unknown required value refuses the run; it does not select a fallback.

## 8. Refusal and fallback policy

### 8.1 Mandatory refusal conditions

C4 must refuse to start or continue an iteration when any of these conditions holds:

- the approved isolation provider/image/runtime identity is missing, changed, unknown, or unverified;
- the OS edition/feature/prerequisite does not support that provider;
- an authoritative feature query is unavailable or returns an unknown state;
- virtualization, hypervisor, memory, disk, CPU, handle, or process capacity is below the reviewed host margin;
- the firewall/network policy does not enforce default-deny for the child identity across DNS, direct IP, proxy, and loopback paths;
- the child token/ACL/AppContainer/capability policy cannot deny the authoritative workspace, AppData, user profile, and unrelated roots;
- the process-tree owner cannot reject breakaway and prove all descendants killed/reaped;
- the fixed executable/interpreter/linter/plugin/config/environment/cwd identity is unpinned or changed;
- the execution grant or its source/workspace/epoch/isolation binding is missing, stale, replayed, expired, or wrong-scope;
- the input or output manifest/signature/hash/path/count/byte policy fails;
- the C3 exact-diff path or no-auto-apply proof is unavailable;
- required host policy (App Control, antivirus, enterprise management) rejects or materially changes the boundary;
- any required probe or acceptance test is skipped, red, flaky, or inconclusive.

Refusal must launch zero processes where preflight can detect the condition. For a mid-run failure, the boundary owner must first terminate/reap the tree, then record the typed terminal state. If tree termination cannot be proven, the state is `uncertain`, reconciliation is required, and no retry occurs.

### 8.2 No silent downgrade

There is no automatic fallback from A/B/D to E/F, from E/F to H, from a VM/container to a host directory, or from a signed/hash-bound channel to an unsigned channel. A different boundary is a different threat model and requires:

1. a separately reviewed decision;
2. a new or updated approved isolation identity;
3. a new execution grant;
4. a new complete §11 proof run; and
5. explicit reconciliation of any uncertain prior state.

The only safe fallback from an unavailable boundary is **no execution**: preserve truthful state, offer a clear remediation message, and wait for a qualified host or approved baseline.

### 8.3 Cleanup and data minimization

- Destroy/dispose the VM/container/distro or close the closed Job after the outcome is durable; retain only bounded metadata needed for reconciliation.
- Keep returned artifacts quarantined and untrusted until transfer authentication and C3 review succeed.
- Do not retain host crash dumps, guest logs, source snapshots, or environment dumps by default; if policy retains them, apply the journal’s bounded/private retention rules.
- Never write, delete, or recreate `steward.db` or `secret.key`.

## 9. DECISION and what would change it

### 9.1 Decision

**DEFER C4-I2 and keep C4 BACKLOG.** C4-ISO does not select a supported Windows isolation primitive on this host because the evidence does not establish one that can satisfy all 20 criteria here.

The decision is not “use the least invasive available API.” The active hypervisor does not make Hyper-V usable on Home; resolvable Job/AppContainer exports do not make a same-kernel boundary sufficient; a `docker-desktop` WSL registration is not an owned baseline; and the current firewall policy is not default-deny egress. The only currently available mode is Python-only/no-boundary, which the binding review explicitly rejects.

### 9.2 Evidence chain

1. The binding review requires an OS-enforced boundary and all 20 criteria.
2. The host is Windows 11 Home Single Language.
3. Microsoft excludes Home from Windows Sandbox and lists client Hyper-V enablement for Pro/Enterprise.
4. Authoritative optional-feature queries were elevation-blocked; CBS package metadata cannot fill the gap.
5. A hypervisor and one Docker-managed WSL registration exist, but neither proves an eligible project baseline.
6. The session is non-elevated with a limited token; no boundary was constructed.
7. Firewall is enabled but allows outbound and reports GPO-store rule behavior; no default-deny egress proof exists.
8. No candidate passed the required proof suite; no candidate is presented as proven.

### 9.3 What would change the decision

Any one of the following could open a new decision batch, but none alone closes it:

- **Supported Windows Sandbox host:** Windows Pro/Enterprise (or another Microsoft-supported edition), Sandbox enabled and authoritatively confirmed, sufficient capacity, disabled networking, read-only input mapping, disposable lifecycle, and a protected return-manifest signer.
- **Supported Hyper-V host:** Windows Pro/Enterprise or Windows Server, role and management stack confirmed, pinned guest image/broker/key, isolated networking, and complete guest lifecycle/resource proof.
- **Qualified Windows container host:** authoritative feature/runtime confirmation, pinned Windows base image and utility-VM/process isolation mode as appropriate, default-deny networking, mount/image policy, and complete resource/tree/transfer proof.
- **Proven host-local composite:** a dedicated design demonstrates all 20 criteria on a same-kernel baseline, including real default-deny DNS/direct-IP/proxy/loopback behavior, complete ACL/root denial, breakaway-proof tree ownership, every resource/scratch/output cap, and protected artifact provenance. This would also require explicit acceptance that same-kernel residual risk is in scope.
- **Audited third-party baseline:** a specific pinned product/image/IPC trust model passes the full review and §11 proof.
- **Dedicated qualified WSL2/Linux guest:** a project-owned immutable/reproducible distro with no host mounts/interop, default-deny networking, approved Linux executable/dependency identity, protected transfer broker, and full proof. This changes the approved execution profile and cannot silently inherit Windows approval.

A changed answer must name the exact baseline, provider identity, threat-model change, and new evidence. “The API exists,” “a hypervisor is active,” or “the command ran once” is insufficient.

## 10. Residual risks and open questions

1. **Supported-host placement:** the project has not documented whether production use will target this workstation, another Windows host, Windows Server, or a managed CI runner. The selected baseline follows that decision.
2. **Windows Sandbox return authentication:** Microsoft documents a disposable VM and configuration, but this research did not establish a protected signer/attestation path for returned artifacts. A future Sandbox design must solve §5 without exposing a host command channel.
3. **Container mode:** process-isolated versus utility-VM-isolated Windows containers has materially different threat models. The exact mode, base image, networking stack, and mount policy remain open.
4. **Same-kernel acceptance:** if E/F is pursued, the threat model must state whether kernel/OS compromise or exploitation of shared services is out of scope. “Restricted token” alone is not a kernel boundary.
5. **Loopback and side channels:** default-deny tests must distinguish ordinary outbound traffic from DNS, direct IP, proxy, loopback, local service discovery, IPv6, host bypass techniques, timing, and shared services.
6. **Reparse and external actors:** ACL/path checks can be raced by a cooperating host-side process. The proof must define whether that actor is in scope and use handles/ACLs/VM boundaries accordingly.
7. **Dependency/interpreter trust:** the exact application-owned interpreter and any linter/plugin/config remain unselected (review open questions 3–5). A pinned executable does not make its loaded code trusted.
8. **Host policy:** enforced App Control for Business and unknown antivirus/enterprise controls may block a future runner, guest tooling, or test binaries. Compatibility must be measured, not assumed.
9. **Capacity:** only 568–885 MB physical memory was available across read-only observations during this research. The project has no approved host-margin/refusal thresholds (review open question 7).
10. **Credential isolation:** VM/container/AppContainer identities and broker credentials need a lifecycle that prevents cross-run reuse and host credential access.
11. **Observability:** host-side capture must not itself create an unbounded queue, disk sink, or timing side channel.
12. **C3 interaction:** the transfer must preserve exact-diff semantics. Bounded excerpts alone may be insufficient to produce a valid patch; the artifact path and patch encoding need a future explicit design.

## 11. Proposed refinements to review §11 (non-binding)

These are proposed clarifications for a future review revision. C4-ISO does **not** alter `docs/self_healing_review.md` or claim that the existing criteria were weakened.

### 11.1 Add explicit transfer provenance to criterion 1

Suggested addition: the approved boundary must provide a pinned identity for the guest/container/runner and a trusted broker that binds the input manifest root, run/grant/isolation identity, and returned artifact-manifest root. Hash equality alone is not provenance; returned bytes remain untrusted.

**Reason:** the review asks how artifacts are authenticated without a host command channel but §11 does not explicitly require a test of that property.

### 11.2 Split “isolation proof” into filesystem and network evidence

Suggested subproofs:

- filesystem: authoritative workspace, AppData, user profile, unrelated roots, alternate data streams, device/reparse targets, and mapped-host paths;
- network: DNS, direct IPv4 and IPv6, configured proxy, loopback, local discovery/service paths, and any permitted broker channel.

**Reason:** one combined pass/fail can hide a missing egress vector or an overbroad filesystem grant.

### 11.3 Require resource-cap ownership and measurement

Suggested addition: every cap in criterion 3 must name its external enforcer, measured value, trigger threshold, and host margin. Scratch and output caps must include all writable artifact locations, including temp files, crash dumps, logs, and retained guest/host volumes.

**Reason:** “bounded” without an owner and measurement point is not falsifiable.

### 11.4 Require an authoritative host-qualification record

Suggested addition to criterion 20: the proof run records OS edition/build, authoritative feature states, isolation provider/image/runtime identity and hash, virtualization status, network policy, enterprise-policy constraints, available capacity, and all refusal thresholds.

**Reason:** API availability and an active hypervisor are not equivalent to an eligible, pinned baseline.

### 11.5 Strengthen crash recovery with process identity

Suggested addition to criterion 14: the durable intent records the boundary instance identity and child/job/process identifiers sufficient to verify that the exact launched tree is stopped; recovery refuses if identity cannot be established.

**Reason:** “uncertain” plus a generic kill is not proof that the prior tree is gone.

### 11.6 Make the no-downgrade rule normative

Suggested addition: if the approved isolation identity is unavailable, unverified, policy-blocked, over capacity, or fails any proof, execution is refused. No fallback to a weaker boundary, unsigned transfer, or Python-only subprocess is permitted without a separately reviewed decision and a new grant.

**Reason:** this makes §10.2’s residual-risk guidance directly testable.

### 11.7 Clarify hash and trust semantics

Suggested addition: hashes prove byte identity only. Returned artifacts are untrusted regardless of matching hashes and may reach the patch proposal path only after boundary/manifest authentication and still require the existing single-use exact-diff C3 approval.

**Reason:** this prevents “hash verified” from being misread as “safe to apply.”

## Evidence index

- Binding requirements: `docs/self_healing_review.md` §§4, 7–11.
- C4-I1 controller and its proof: `agents/healing_controller.py`, `test_healing_controller.py`, `PLAN.md` lines 496–523.
- C3 exact-diff and single-use approval: `agents/patch_review.py`, `PatchReviewManager.propose`, `.approve`, `._consume_approval`, `.apply`, `._apply`.
- Durable journal/write-ahead precedent: `agents/file_agent.py`, `FileAgent._begin_mutation`, `._complete_mutation`, `._save_operation_log_locked`; `agent/journal_lock.py`, `operation_journal_lock`.
- C3-R stdlib AST/token dependency precedent: `PLAN.md` lines 318–328; `docs/ast_patch_review.md`.
- FS-S5 stdlib/OS dependency precedent: `PLAN.md` lines 152–175.
- Official mechanism references:
  - [Windows Sandbox overview](https://learn.microsoft.com/en-us/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-overview)
  - [Hyper-V system requirements](https://learn.microsoft.com/en-us/windows-server/virtualization/hyper-v/system-requirements-for-hyper-v-on-windows)
  - [Job Objects](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects)
  - [AppContainer isolation](https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-isolation)
  - [Windows Firewall rules](https://learn.microsoft.com/en-us/windows/security/operating-system-security/network-security/windows-firewall/rules)
  - [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking)

## Final disposition

- **C4-ISO:** research decision complete.
- **Decision:** DEFER; no supported baseline selected on this host.
- **C4-I2:** not started; no executor, sandbox, transfer implementation, tests, dependencies, GUI wiring, or runtime behavior introduced.
- **C4:** remains **BACKLOG**.
- **Next trigger:** a supported host or explicitly approved candidate baseline enters a new focused design/proof batch.
