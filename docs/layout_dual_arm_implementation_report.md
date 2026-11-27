# Layout / Dual-arm integrated implementation report

## Review checkpoint for main push — 2026-11-27

User requested a runnable review checkpoint before issuing a new plan.
Fresh source suites: Python3.12 **1941 passed, 31 skipped** (40.14s),
Python3.11 **1941 passed, 31 skipped** (34.44s). Public schema regeneration
check and whitespace checks pass. Fresh wheel built under
`/tmp/brain-layout-push-20261127/dist/`; installed outside the checkout, both
wheel smoke scripts pass. An isolated aiohttp HTTP server using that installed
wheel starts and responds to `/health` with HTTP200. The initial ad-hoc smoke
configuration was rejected for missing uint32 scene IDs and then missing model;
the corrected Web configuration passes without model or Control execution.

This checkpoint is startup/code-regression verified, not certification of all
physical/dual-arm workflows. Default services still do not advertise or dispatch
v4. Real Control v4 negotiation, trusted dual visual assignment and remaining
live continuity gates stay open in the acceptance audit. No production service
restart accompanies this push; runtime logs, credentials and external repos are
not part of the commit.

## Latest verification checkpoint — 2026-11-27 quantity range

D14 evidence is now mapped to named tests rather than aggregate counts:
`test_unregistered_cooperative_skill_never_exports_or_changes_runtime`
checks pour/handover/cooperative_grasp through recipe and mocked Qwen routes,
with no Commands export, pending dispatch, scene or arm-state mutation and no
hidden fallback. `test_two_ordinary_acquisitions_cannot_disguise_handover`
checks conflicting acquisition during an explicit hold, both initially held
and acquired in the current segment. The five related dual test modules pass
**52 tests on Python3.12 and Python3.11**. These eight newly added cases do not
change production code and are not included in the older full-suite counts
below. Real U semantic routing for cooperative requests remains unverified;
the hold tests do not establish that arbitrary missing-hold model output is
detected. No Control calls, production restart, commit or push were made.

Application-restart layout uncertainty coverage added in
`brain_tests/test_layout_application_recovery.py`: simulated timeout before
platform application and lost acknowledgement after platform application both
persist unknown. A newly constructed application/platform restores the same
scene snapshot and retired ID bound, rejects a fresh layout with
scene_sync_unknown, and emits no new platform load/patch, receipt or Commands.
This proves persisted application behavior under controlled faults, not a live
Gateway disconnect test. Real unknown/pending restart exercise remains open.

Latest packaged checkpoint (supersedes older wheel/source counts below):
Python3.12 **1931 passed,31 skipped** (39.74s); Python3.11 **1931 passed,31
skipped** (33.58s). `generate_layout_schemas.py --check` and diff whitespace
checks pass. `uv build --wheel --out-dir /tmp/brain-layout-release-contract-20261127/dist`
produced robot_agent_brain-0.1.0-py3-none-any.whl, SHA256
`64d6db7f1974598eaf2de49745a2933f6bbe68fa93476550db33812a39fa7575`.
Installed into independent3.12/3.11 environments; from `/tmp`, both wheel_smoke
and wheel_understanding_smoke pass. Smoke now verifies installed explicit-radius
rejection and application contract defensive copying as well as schemas/prompts,
CLI/Web imports and replay. Replay artifacts: `/tmp/brain-wheel-smoke-2dar64il`
(3.12), `/tmp/brain-wheel-smoke-vumhqd9v` (3.11). These are offline installation
checks, not real Control execution. Production services unchanged.

Protocol mismatch follow-up: an explicitly advertised v4-only controller can no
longer receive a plan from a legacy3.0 Profile. Pipeline rejects the mismatch
before arm assignment or skill planning in both recipe and Qwen modes, with no
Scene changes or Commands export. No-advertisement v3 replay remains unchanged.
Python3.11/3.12 dual session/v4/application/compatibility suites:32 passed each.
This is version validation only, not live v4 dispatch implementation.

Full application-path fix: extending the contract test to `app.handle()` exposed
the old unconditional `control_dual_arm_not_ready` gate even with an explicit
valid v4 advertisement. The gate now allows planning after validating that
advertisement, while default/no-contract behavior remains closed. Existing
Session/Profile/grounding checks remain and v4 dispatch is still refused.
The public handle test now verifies one U/one S, saved4.0 Commands and Scene
digest equality, unchanged scene/held state and executed=false. Missing/v3-only
contracts stop before bootstrap and create no original or Commands. Both
Python3.11/3.12 application/Web/composite/bootstrap regressions:44 passed.
This is fixture-backed application integration, not a live Control advertisement
or a real dual execution test. Production has not been restarted.

Application planning-contract boundary added: `BrainApplication` accepts an
explicit adapter-supplied `control_skill_contract`, validates before expensive
initialization, and deep-copies nested data into Pipeline. DefaultNone remains
unsupported. Tests prove dictionary/model mutation isolation, invalid-advertisement
early rejection and v4 planning through an application-created session, while
dispatch still refuses4.0. Application/artifacts/v4/Web regression:50 passed
on each of Python3.11/3.12. Fixture contract only: no production discovery or
Control protocol support is claimed. Source update is newer than the latest
1922-test full-suite checkpoint; no service reload or wheel rebuild this turn.

Latest real-Qwen dimension smoke: `scripts/smoke_layout_understanding.py
--config var/layout-dual-audit/web-20261127-01/brain.json --round-dimensions
--output-dir var/layout-dual-audit/round-dimensions-20261127-01`.
Circle radius0.2m, ring bounds0.1/0.2m and arc radius0.2m/angle90° all passed
first attempt, each with exactly one HTTP request/one U call and exact six
apples. Saved full wire requests, raw outputs, canonical parameters and server
timing/usage. No Scene publication, camera or Control call. This confirms three
understanding examples only, not browser/end-to-end execution. The standalone
catalog fingerprint is6d540c26… (no runtime registered-profile enrichment),
so timings must not be conflated with browser cataloge608c3b5… measurements.
Latest full source suites: Python3.12 **1922 passed,31 skipped** (37.17s),
Python3.11 **1922 passed,31 skipped** (31.67s). Wheel remains older as recorded.

Explicit round-pattern provenance: layout entry now validates named radius,
inner/outer radius and arc angle alongside center/edge spacing before planner or
ID allocation. Chinese/English unit conversion and longest radius labels avoid
interpreting ring bounds as a generic circle radius. Missing/mismatched values,
wrong units and unsupported numeric syntax are rejected, never rewritten.
Tests cover unchanged canonical output, radius/angle loss and pre-allocation
rollback. Layout/transaction/composite regression:86 passed each on Python3.11
and3.12; feedback classification:13 passed on3.12. A first attempted command
named a nonexistent geometry test file and collected no tests; corrected test
paths produced the counts above. Existing physical-radius transaction tests
verify resolved positions, not only schema acceptance. No production reload.
These are narrow explicit-dimension guards, not unrestricted natural-language
quantity/negation parsing or a claim of full numeric-provenance coverage.

Explicit-spacing provenance follow-up: the observed browser phrase
“中心间距固定为1厘米” did not match the old numeric preservation guard (the real
U happened to preserve it). The guard now covers fixed Chinese/English wording
and distinguishes explicit edge spacing from center spacing. It rejects changed
values, changed modes and unsolicited auto spacing; it does not repair model
output. Pipeline tests verify rejection before ID reservation or scene mutation.
Both Python3.12 and3.11:82 targeted layout/quantity/original tests passed.
This is intentionally not a claim of complete numeric provenance validation:
radius, arbitrary quantity wording and unrestricted natural-language scope still
need separate coverage. This change is newer than the full regression below.

Latest source regression after collision feedback and v4 preflight changes:
Python3.12 **1897 passed,31 skipped** (37.47s), Python3.11 **1897 passed,31
skipped** (33.26s), with `pytest -q -o addopts='' --tb=line`.
The earlier wheel remains at its explicitly recorded1891-test source checkpoint;
these two changes have not been deployed to production or repackaged yet.

Protocol preflight ordering fix: the pipeline previously resolved arms before
`plan_v4` validated Control's advertised contract, potentially requesting visual
assignment even when v4 could not be consumed. Shared `require_v4_contract` now
runs before arm resolution and remains in the standalone planner entry point.
No contract, v3-only contract and invalid feature flags are regression-tested
with an unlocked arm: no assignment call, no Commands and unchanged Scene.
Python3.12 targeted58 tests pass; Python3.11 targeted64 (including legacy dual
session and v4 compatibility) pass. Actual Control/bridge source still consumes
2.0 at HEAD05afa87c…; no live v4 capability has been inferred from this change.

L09 browser collision rollback: request `15279ae2d0024cfb8b8e1e6f69332944`
in session `4f645460df484c1c8c8e0f02fb2d73c5` requested two additional apples,
exact count, fixed 0.01m center spacing, keeping the existing six apples.
Real U preserved these constraints; resolver rejected with
`scene_layout_collision`, category `geometry_layout`. Fresh Gateway captures
before/after have identical raw Scene, version1 and digest af9b27e2…;
original SHA256 stays7555f1cd…; no Commands or new publication transaction.
Evidence: `web-20261127-01/collision-grid-before/` and `collision-grid-after/`.
The UI's generic layout explanation obscured the collision reason, so specific
collision and workspace feedback was added, retaining error codes and refusal.
Targeted tests:10 passed on Python3.11 and3.12. This feedback-only source update
is newer than the full-suite/wheel checkpoint below and not loaded into services.

Latest L01 browser acceptance: refreshed isolated Brain8503 PID3410191;
session `4f645460df484c1c8c8e0f02fb2d73c5`, task
`1bb632f3ad7049aca09fb4d56e506001`. Input HTTP task31 contained Scene0,
version0, zero objects. “在桌面新增六个苹果，排列成两行三列” succeeded first attempt:
one U, deterministic planner, six apple IDs8–13, exactly2 Y rows/3 X columns,
actual and structured auto spacing0.084732012m, committed version1.
Camera5 PNG640×480 visually inspected and digest-matched:
`af9b27e2b7fddb21341757ba4de4539b13ea62d434e52c1fa9c3f40a3bfa7fad`.
Evidence `web-20261127-01/grid-latest-browser-success/`; no Commands or Control
calls. Production8500/8099 unchanged. Prior failed six-apple attempts remain
in the historical aggregate; this does not erase those failures.

Missing-surface browser check: task `64e715a1b9af47edad7cf12c8fc43c90`
requested two bananas on an existing coffee table, explicitly forbidding table
substitution or creation. Real U returned clarification: no coffee table exists.
One understanding call, no Commands or Scene commit. Gateway readback equals
the prior raw Scene (version1, digestf9ce076e…); original SHA256 remains69345d73… .
Fresh camera5 screenshot and full verification saved in
`var/layout-dual-audit/web-20261127-01/missing-surface-after/`.
This is semantic-stage missing-support evidence, not a claim that the browser
exercised Python's unresolved-reference exception. Resolver/initialization
targeted regression separately passed12 tests.

Current release checkpoint (supersedes earlier source/wheel counts below):
Python3.12 **1891 passed,31 skipped** in37.34s; Python3.11 **1891 passed,31
skipped** in31.71s. Schema drift and whitespace checks pass. Wheel rebuilt at
`/tmp/brain-layout-final-audit-20261127/dist/robot_agent_brain-0.1.0-py3-none-any.whl`,
SHA256 `39bd1ea34fb8b9ca93b6ce7c831c075472f536d95669283d0c975a9a86c1d39e`.
Installed into independent3.12/3.11 environments; from `/tmp`, both wheel_smoke
and wheel_understanding_smoke pass. Replay artifacts:
`/tmp/brain-wheel-smoke-al03nt9o` (3.12), `/tmp/brain-wheel-smoke-vmckszbw` (3.11).
This checkpoint includes idempotent HTTP replay, contract preflight, geometry
error classification and structured resolved spacing. No live Control calls;
browser/service evidence retains its own earlier runtime revision.

Resolved-spacing audit fix: automatic line/grid/checker/alternating spacing
was previously recorded only in result assumptions, leaving the dedicated
`LayoutResolution.adjusted_spacing_m` empty. The private SceneEditResult now
carries the actual resolved automatic spacing; pipeline copies it and all
resolver assumptions into LayoutResolution. Replacement forwards the private
metadata from its validated rearrangement preview. Fixed spacing remains null
in the adjustment field; it is not misreported as an automatic change. Tests
compare the structured value against actual committed object separation, and
check quantity-search assumptions are also present on the resolution.
Layout transaction/quantity/original regression: **66 passed** on3.12/3.11.
Production service/wheel have not been refreshed for this metadata fix.

Replacement scope rechecked: layout uses the existing SceneEditor `_replace`
implementation. Replacing an object with dependent children/support objects
still follows the existing explicit refusal policy, not an invented unsafe
reference rewrite. Original-basis append/rearrange/replace already have frozen
membership and restart tests (`test_original_arrangement_continuity.py`);
earlier stage-table wording about that implementation being absent is stale.

Reproducible saved-task aggregation added in `scripts/report_layout_dual_audit.py`.
Command: `python scripts/report_layout_dual_audit.py --tasks-root
var/layout-dual-audit/web-20261127-01/tasks --output-dir <new-directory>`.
Latest output `var/layout-dual-audit/aggregate-20261127-02/report.md` and
`report.json` includes30 task reports, no read errors:24 service-reported
successes,2 geometry safe refusals,2 scene-sync failures,1 runtime validation
failure and1 reference/selection failure. These counts include historical
pre-fix attempts, not30 acceptance passes. Every recorded model call retains
stage/status/tokens/timings/cache counts and request/Prompt/Schema fingerprints;
missing timing is null, not0. Original error/category and result-file SHA256
are retained, with separate audit classification. The script does not execute
or modify tasks. Four tests passed on both3.11/3.12. This aggregation covers
saved Web task reports only; standalone U/S smoke and independent visual/
geometry verifications remain separately referenced, not silently counted here.

Real idempotency audit uncovered a Web ordering defect: replaying the exact
original first-turn request after bootstrap returned400
`browser_scene_identity_invalid` before reaching the durable task receipt.
Added read-only `TaskStore.matching_request` with the same canonical payload
fingerprint as submit. HTTP start checks active browser/session and uncertainty,
then exact prior request before comparing its old Scene to current state.
Fresh requests still validate current Scene; changed payload under the same key
still conflicts. No prior request is adopted/requeued.
Real task28 replay after isolated Brain restart (PID3403741,8503) returns200,
same taskID28, terminal=true. Task count29, session_state SHA256, original SHA256
and Gateway transaction file list are unchanged. Evidence:
`web-20261127-01/request-replay-before-fix/` and `request-replay-after-fix/`.
Web regression **21 passed** on Python3.12/3.11, including empty-bootstrap replay,
modified payload, different browser, and fresh stale-scene rejection.
No production service changes or Control execution. Latest wheel/full regression
counts below predate this Web fix.

Contract gate follow-up: `ControlSkillContract` now rejects mixed expansion
levels at snapshot validation, including unused registered skills; feature
advertisements require explicit booleans, and protocol lists reject duplicates,
blank or whitespace-padded versions. Unknown future versions remain readable
but do not authorize v4. `plan_v4` checks advertised4.0 before Recipe/Qwen,
not only after a draft is produced. Tests verify v3-only requests cause zero
skill-model/recipe calls, no exports and no Scene mutation. Contract/pipeline/
resource/hold suites: **52 passed** on3.12 (0.21s) and3.11 (0.17s).
This does not add a live Control v4 endpoint or change the dispatch refusal;
real capability negotiation remains incomplete. Latest wheel/full-suite results
below predate this contract-gate patch.

Exact-capacity browser rejection also verified: task
`a3e04085ae0b4e0f97110c9e146a6d43` in the same isolated session requested
ten additional apples with immutable 30cm spacing and exact count. One U call,
`scene_layout_capacity_exceeded`, no Commands, no commit. Gateway before/after
raw Scene documents are identical (version1, subversion0); original file SHA256
remains `69345d73029b7367276d7f96485ad45f8157b5e7912c3a08ce81cb53f234b2e3`.
Fresh captures are under `exact-capacity-before` / `exact-capacity-after` within
the web audit directory. Capture metadata intentionally names the last successful
publication; `verification.json` separately identifies the failed task.

This real run exposed a reporting bug: capacity refusal was categorized as
`semantic_protocol`. `_issue` now classifies the three explicit layout geometry
errors (collision/capacity/workspace) as `geometry_layout`, retaining original
codes and refusal semantics. Seven tests cover the new category and unchanged
schema/asset-choice error categories. The running service and historical result
were NOT rewritten; real-browser category retest remains pending.
Full suites before this category patch: **1859 passed, 31 skipped** on both
3.12 (37.27s) and 3.11 (31.53s). Category tests:7 passed on3.12;
category+quantity:17 passed on3.11. The prior wheel predates this small patch.

Browser acceptance added: isolated Brain restarted at PID3400471 (8503),
Gateway8096 and browser5176 retained; production8500/8099 unchanged.
Session `e0b44a19411b4f4abbb206c79bad603b`, task
`441f12fba0a14fa39e62b14a032b5492` requested ten apples, permitted two through
ten and required fixed 30cm centre spacing. First attempt succeeded with five
apples at x=-0.6,-0.3,0,0.3,0.6, y=0: six deterministic quantity candidates,
one U call, no S/vision/Control calls, one committed Scene version (1).
Gateway camera5 RGBD PNG640×480 and published readback digest match:
`f9ce076ea5423cac3805f7e3603166ae16dcd398d5bd5403e71e2b3b25e6a27b`.
Screenshot visually inspected. Evidence:
`var/layout-dual-audit/web-20261127-01/quantity-range-browser-success/`.
U input18506/output281 tokens, input7.911s/output6.989s, U elapsed15.332s;
reported pipeline elapsed16.114s. These are one-sample observations, not a benchmark.
The verification helper initially used the wrong Scene parser twice; both failed
before evidence output. Final assertions use the lossless document's typed view,
and compare digest against raw JSON. The user task was not retried.

Quantity regressions now **10 passed** on both Python3.11/3.12, including
non-geometry failures making only one attempt, failed append preserving existing
receipts/membership, and the next successful append using fresh IDs after the
failed reserved range. Latest full-suite results below predate these four added
test cases; production source is unchanged by these test additions.

- Python 3.12 full regression: **1855 passed, 31 skipped**, 37.06 seconds.
- Python 3.11 full regression: **1855 passed, 31 skipped**, 31.63 seconds.
- Quantity-search regressions: **6 passed**, including append preserving existing
  members/slot bindings, one commit, reserved ID tail and request replay.
- Generated-schema drift check and `git diff --check`: passed.
- Real Qwen read-only Compact U: **3/3 first attempts passed** for preferred
  count with explicit bounds, bounds without preferred count, and exact quantity
  with automatic spacing. Evidence: `var/layout-dual-audit/quantity-range-20261127-01/`.
  Requests/raw responses/canonical payloads are saved per case; no scene was
  published and Control was not called. This is not browser geometry acceptance.
- The latest quantity wheel has been rebuilt and installed into both isolated
  Python environments. Both `wheel_smoke.py` and `wheel_understanding_smoke.py`
  passed outside the checkout, including bounded quantity candidate order and
  lossless Compact range round-trip. SHA256:
  `dc77cbce3116e51e26e87dc5ef6f3e43defa28b1e5ed6a9345659f7b204bccd2`.
  Wheel: `/tmp/brain-layout-quantity-release-20261127/dist/robot_agent_brain-0.1.0-py3-none-any.whl`.
  Replay artifacts: `/tmp/brain-wheel-smoke-433oesj2` (3.12),
  `/tmp/brain-wheel-smoke-nvpqlv4z` (3.11). No live model or Control calls.
- Live Control v4 negotiation and execution remain unverified. Current local
  bridge accepts only 2.0; application wiring does not discover/inject a real
  `ControlSkillContract`. Existing v4 planning tests use explicitly labelled
  fixture contracts, not a controller capability declaration.

## Stage status

| Stage | Status | Evidence |
|---|---|---|
| P0 | partial | Existing SceneEditPlan, Atomic v2/v3 regression is green; live Control v4 capability and skill contract are not yet available |
| P1 | partial | `ArrangementSpec`, strict wire parse and one-call composite semantic reuse implemented; real-model routing acceptance pending |
| P2 | partial | Deterministic patterns, path/font sampling and restricted Qwen custom-draft HTTP path; complex text shaping and real-model acceptance remain incomplete |
| P3 | partial | Candidate transforms, automatic spacing/bounded quantities, current/original append/rearrange/one-to-one replace, durable IDs and frozen membership pass local transaction tests; replacement of dependent parents retains the existing explicit refusal policy; broader browser acceptance remains incomplete |
| P4 | partial | Explicit/held locks, transitive cross-object same-arm groups and revision-bound visual assignment integrated with audited fallback; real visual evidence acceptance pending |
| P5 | partial | Atomic IR, strict drafts, DAG builders and adapter-snapshot skill/granularity validation; live capability discovery and dispatch remain incomplete; no silent v4→v3 downgrade |
| P6 | partial | Web one-call composite semantics and durable phase evidence tested with mock Gateway; live browser/Control and crash recovery acceptance pending |
| P7 | partial | Current Python 3.11/3.12 full suites and rebuilt wheel offline smoke pass on both interpreters; live Qwen coverage is partial, Control/browser and performance gates pending |

The detailed sections below are chronological checkpoints; later sections supersede
earlier limitations and test counts. The table above reflects the current status,
not a claim that local planning tests prove real execution.

## Compatibility

- Full task-understanding envelopes and historical replay remain supported.
- Compact U adds `scene_layout` (`at`) without changing existing short codes.
- Single-arm Atomic v2 and staged dual-arm v3 paths are unchanged.
- Control/IK/collision remains outside Brain.

## Verification

```bash
PYTHONPATH=. conda run -n robot_agent_integ pytest -q
conda run -n robot_agent_integ python -m compileall -q src/robot_agent_brain
conda run -n robot_agent_integ python -m pip wheel . --no-deps -w <temporary-dir>
```

The full-suite run after original layout routing passed in `robot_agent_integ`
(Python 3.12), with existing skipped tests. An initial run exposed an optional
layout-field compatibility issue in the lightweight capability-check fixture;
after correcting that read, the complete rerun exited 0. Real dual-arm parallel
execution is not claimed until Control negotiates Commands v4 and the corresponding
runtime capability.

## Control skill contract validation seam

`ControlSkillContract` and `build_negotiated_commands_dag` validate an explicitly
provided adapter snapshot before returning v4 Commands. They enforce advertised
protocols, contract revision, registered skill names, parameter JSON Schemas,
one expansion level and optional resource/sync/hold capabilities. External schema
references are rejected to keep validation offline. This is a Brain adapter seam,
not an assertion that the current Control server publishes this contract.

A source search of local Control/bridge code (excluding vendored libraries and
runtime outputs) found no `skill_contract_revision`, `expansion_level`,
`commands_dag` or `supported_protocol` interface. Production v4 dispatch therefore
remains disabled. Twenty contract/builder tests pass, including v3-only refusal,
mixed granularity, unknown skills, invalid arguments and stale revisions. Live
capability discovery, runtime planning selection and feedback remain unfinished.

## Latest exact-placement evidence

`brain_tests/test_layout_transaction.py` checks actual candidate transforms,
not merely normalized planner metadata: grid spacing, circular physical radii,
off-centre anchors, capacity rollback, one version increment and the public
`BrainPipeline.process_turn` entry point. These are local tests, not browser
or Control acceptance evidence. `world_positions` now records the actual
candidate positions rather than a full-table projection.

Public schemas are generated by `scripts/generate_layout_schemas.py`; use
`--check` to detect drift. They are included in the wheel through Hatch's
force-include mapping. v4 parsing supports replay, while live dispatch currently
returns `unsupported_protocol_version` until negotiation and feedback are wired.

## Original layout session routing

`BrainSession.process_turn` now derives original-basis layouts through the existing
immutable snapshot/reset transaction. It validates candidate geometry before
publishing, remaps layout instance IDs and slot bindings to the new branch, and
records the confirmed branch identity without applying the old patch a second time.
The existing reset authorization, pending-execution and held-object guards remain.

Targeted tests: layout transaction + original commit (16 passed); layout route,
patterns, paths, original application/recovery and schema exports (44 passed).
The new regressions verify repeated derivation, immutable original bytes, disjoint
new object IDs, result validation and capacity-failure rollback. These do not prove
browser publication, composite execution or dual-arm Control acceptance.

## Current-branch append

Append treats `items.requested_count` as the additional count. The new slots use
the explicitly requested pattern/region and undergo normal support and collision
checks; no existing object is moved to make space. Slot identifiers are allocated
without overwriting prior bindings. The combined arrangement record is saved only
after the scene patch succeeds, and existing world-position evidence is refreshed
from the current scene. Missing arrangements, branch mismatch and deleted members
are refused rather than matched by name. Duplicate current-branch `create` cannot
overwrite an existing arrangement. Confirmed request replay is handled by the
receipt mechanism described below.

`test_layout_transaction.py` verifies successful append, preserved existing scene
objects, combined membership, collision rollback and duplicate/missing-arrangement
refusal, serialized membership restoration, deleted members and branch isolation.
Current targeted run: 15 passed. The full suite after append integration exited 0
with existing skips; the last additional membership regression passed in the
targeted run. New membership errors have specific user-facing explanations.

## Current-branch rearrangement

Rearrangement consumes the arrangement index's existing slot-to-instance mapping.
It preserves IDs, asset metadata, display names, color/unknown components and
world scale; pose changes are converted back into the existing parent frame.
Only Transform and support metadata are patched, with one final transaction.
Collision checks use the complete proposed member configuration, not intermediate
positions that other members are about to vacate. Assets are read from existing
instances; a request to change their semantic asset is refused instead of silently
being treated as replace. Nested arrangement members and platform objects are
currently explicitly unsupported. Membership and count mismatch remain errors.

Local tests verify preserved identity, color, scale and allocator, changed positions,
single version increment, asset-change refusal and capacity rollback. This is not
yet browser or natural-language acceptance evidence.

## Current-branch one-to-one replacement

Layout replace now uses the existing SceneEditor replacement helper in a private
SceneManager preview, then uses exact layout placement before producing a single
patch. No intermediate preview version is published. New asset IDs replace old
members under the same slot keys, and deleted IDs are exposed to dialogue cleanup.
Replacement retains existing support/platform/dependent-object guards. It does not
yet implement general dependent-reference remapping: such replacements are still
explicitly rejected by the existing helper, rather than leaving dangling links.

`test_layout_transaction.py`: 20 passed, including apple-to-banana replacement,
new IDs, one version increment, refreshed membership, and failure leaving objects,
arrangement metadata and the allocator unchanged. Real Qwen/browser acceptance is
still outstanding.

## Confirmed layout request replay

Accepted layout requests now retain an instruction/payload fingerprint, confirmed
scene digest and serialized result in the session checkpoint. A repeated request
with the same content and unchanged scene returns that result without publishing,
allocating IDs or observing dialogue again. Different content under the same ID
is `scene_layout_request_conflict`; an old receipt after a subsequent scene change
is `scene_layout_request_stale`. Neither refusal mutates the scene.

The 23 layout transaction tests include current/original replay, checkpoint
save/restore, conflicting content and stale-result refusal. This is confirmed
checkpoint replay, not yet proof of crash recovery between platform publication
and session checkpoint: that interval still needs transaction-journal integration
and fault-injection testing before L12 can be considered fully accepted.

## Dual skill draft boundary

Added closed `DualSkillDraft`/`OperationSkillDraft`/`AtomicSkillDraft` contracts.
The v4 builder now rejects model-provided dependencies, arm assignment or resource
fields instead of using or discarding them, and requires exact operation coverage.
Dependencies originate only in Python-owned operation IR and same-arm chaining.
13 DAG/replay tests pass. This fixes a concrete builder boundary violation, but
does not constitute live dual-arm runtime integration: the production pipeline
still selects the legacy dual planner; Control contract negotiation, skill
live capability discovery and v4 execution feedback remain unfinished.

## Atomic first-turn layout bootstrap

The application no longer publishes a default template before validating layout.
It passes a private template to the existing initial-edit transaction, now shared
with layout: validate the complete candidate, load once, record version 1 and
persist layout membership/request receipt. A failed candidate leaves the session
without an initialized scene and performs zero platform writes. No additional
understanding call is made. Tests with a counting local platform cover success,
capacity failure and confirmed replay (25 layout/bootstrap tests passed). These
are application integration tests with a deterministic provider, not live Qwen
or browser screenshots.

## LayoutResolver responsibility alignment

Moved actual candidate generation from SceneEditor into
`LayoutResolver.resolve_candidate`: asset expansion, existing instance selection,
support/anchor lookup, world-space slot mapping, scale/orientation handling,
geometry/capacity validation and private replacement preview. SceneEditor's
`layout_result` is now a compatibility delegate. The resolver reuses existing
editor geometry/replacement policies instead of duplicating their business rules;
it does not publish scenes or call Control. Session transaction handling remains
the only publication path. Direct-resolver tests verify no input mutation and
equivalence with the editor entry point. Projection bounds now reject infinity,
NaN and booleans explicitly.

## Normalized path sampling

Custom/text paths supplied in the spec are now sampled at deterministic equal
normalized arc-length intervals rather than requiring one input vertex per object.
The sampler preserves exact requested count, handles a single object at the path
midpoint, bounds input/output sizes and rejects degenerate or invalid paths.
World mapping and capacity/collision checks still happen in LayoutResolver.
Planner provenance correctly records this Python computation as deterministic;
no Qwen call is implied by a caller-supplied path. Font-outline generation and
live model custom-draft generation are still incomplete.

63 path/pattern/transaction tests passed before the added five-object scene
sampling regression; the complete suite is rerun after that addition.

## Registered font outline layouts

Text without an explicit path now resolves `pattern.font` through deployment
`layout_fonts` (font name → file path). Install optional dependencies with
`pip install -e '.[layout]'`. Example configuration:

```json
{"layout_fonts": {"default": "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"}}
```

Relative font paths in a config file resolve against that file. Model font values
are registry identifiers, not paths. FontTools supplies actual glyph contours;
quadratic/cubic curves are deterministically flattened with 32 subdivisions and
sampled by total contour length without connecting separate contours. Normalized
points preserve glyph aspect ratio; region mapping and geometry checks remain in
LayoutResolver. The planner revision records the font SHA256. Missing dependencies,
unregistered fonts, absent glyphs, empty outlines or excessive contour complexity
are explicit errors, never invented substitute glyphs. This does not yet implement
kerning/shaping for complex scripts, variable-font style selection, or real Qwen
text-layout acceptance. Current runtime configuration is not changed automatically.

## Restricted Qwen custom-layout draft

Custom descriptions without a supplied path now call `QwenHTTPProvider.plan_layout`
through the normal recorded HTTP path, using a closed `LayoutPatternDraft` schema.
The model receives only description/count and returns bounded normalized u/v path
points. It cannot change assets, operation, region or exact count. Python validates
range, length and self-intersection, samples the path, then performs normal asset
and geometry resolution. There is no automatic retry or fallback deleting invalid
fields. Ordinary rules/text/supplied-path plans do not call this model stage.

Five MockTransport tests pass, including the actual provider request builder,
schema/hash audit fields, six-object candidate generation and malformed responses.
These tests do not establish real Qwen structured-decoding compatibility or quality;
that acceptance remains outstanding. The stage is named `layout_planning` and must
be included in later latency/call-count reports rather than hidden in U.

## Parsed composite phase execution

`CompositeTask` validates a sequence of accepted scene phases followed by a robot
phase. `BrainSession.process_composite_turn` consumes their already parsed payloads
without invoking understanding, records per-phase before/after version and digest,
commits each scene phase and grounds/plans against the new current scene. It checks
command scene identity (and digest when present), preserves committed scene phases
on planning failure, marks later phases skipped and refuses blind duplicate replay.
Three real pipeline/session tests cover new instance grounding, retained layout on
missing robot target and skipped robot planning after scene failure.

The direct session entry point is separate from the Web execution path described
below. General mixed-order/recovery workflows still retain their existing
decomposition behavior; full crash/resume acceptance remains outstanding.

## One-call composite understanding and deployment checks

`QwenHTTPProvider.understand_composite` now wraps the existing selected Full or
Compact U schema in a closed phases envelope. The request retains the existing
catalog, workspace and scene context. Each payload is schema checked, decoded
without deleting fields, canonically parsed and checked against the same OLS
snapshot. The ordered task contract requires accepted scene phases followed by
one robot phase. Invalid phase fields produce `provider_output_schema_invalid`
with their actual path; there is no hidden retry or partial application during U.
`BrainSession.run_composite_task` connects this one-call result to the parsed-phase
executor. Both pipeline U entry points refresh the same validated catalog before
constructing their requests.

Five provider/session tests pass: Full and Compact one-call parsing, malformed
payload rejection without retry, and one real session/pipeline run grounding the
robot source to the newly created layout instance. HTTP transport is mocked;
these are not live Qwen or browser acceptance results.

Deployment validation performed in an isolated `/tmp/brain-layout-py311-audit`
environment, without changing running services:

- Python 3.11.14 full source test suite: **1660 passed, 31 skipped** (28.99 s).
- Python 3.12 integration environment full suite, including the added session
  test and revised prompts: **1660 passed, 31 skipped** (33.29 s).
- Wheel built with isolated hatchling, then installed with layout/dev/web/batch
  extras. From `/tmp` (outside the source tree), package imports, packaged layout
  and assignment prompts, all four packaged public schemas and the composite
  Compact schema passed smoke checks.
- The Python 3.11 source regression run is separate from the installed-wheel smoke;
  it is not represented as running the whole suite against the wheel.

Review also corrected two draft prompts: arm assignment now emits only the
dual-arm assignment contract (not the old single-arm-only instructions), and
multi-arm skill planning emits operation-local skill chains rather than model-
generated DAG IDs/dependencies. These prompts still require real model/Control
integration acceptance; correcting their text does not enable v4 execution.

Remaining release gates include real-browser composite acceptance/checkpoint recovery,
Control v4 capability advertisement and execution, complete resource/hold/sync
integration, remaining layout geometry policies, and actual Qwen/browser evidence.
No code has been committed or pushed and no service configuration was switched.

## Web composite semantic reuse and durable phase evidence

For a decomposed scene-edit/layout prefix followed by a robot suffix, a provider
supporting unified understanding is now called once with the complete instruction.
The accepted phases enter the existing application/Gateway transaction executor;
they do not bypass lease, live digest, bootstrap, grounding, policy or dispatch
checks. The robot suffix is represented by one complete robot payload, not multiple
independently planned commands joined afterwards. Other mixed orderings and legacy
failure-chain recovery retain the existing executor. A rejected unified response
does not silently fall back to separately understanding and partially executing
its phases.

The application accepts prepared BrainTurns only from its internal-step interface,
revalidates them and checks the instruction identity. Each child records zero U
calls; the outer result separately includes the unified U and all child model
calls. The initial decomposition call remains a separate D stage.

Before child effects, the durable step ledger stores the complete canonical
phases and unified model evidence. Each child checkpoint records before/after
Scene identity/digest and transaction receipts. On completion the ledger transfers
to ConversationTurn (and FailureChain when applicable) before pending state is
cleared. Previously, reconstruction from the summary discarded this detail;
the authoritative checkpoint is now preserved. Raw provider audit evidence is
excluded from recovery prompts, while canonical semantics and confirmed effects
remain available. Persisted evidence alone does not authorize automatic crash
replay.

Five new Web orchestration tests use an explicit in-memory browser/Gateway HTTP
double, not a real WebEditor: unified U plus edit/plan, layout/new-object planning,
invalid U with no first-phase commit, robot binding failure preserving the edit,
and rejection of prepared payloads at the external application entry. Tests also
reload persisted conversation ledgers and compare phase Scene continuity. These
tests do not establish actual Control v4 execution or browser visual correctness.

After this integration: Python 3.12 full suite **1665 passed, 31 skipped**
(34.21 s); Python 3.11 full suite **1665 passed, 31 skipped** (29.61 s).
The prior recovery unit double was updated to declare its absent Scene explicitly
because phase checkpoints now read Scene identity. No recovery assertion was
removed or relaxed. The Web checkpoint test also inspects the saved state before
each child starts, proving canonical phases exist before the first commit and the
first commit is checkpointed before robot planning.

## Negotiated v4 Pipeline path (planning only)

An explicit dual `RobotProfile.commands_version="4.0"` now routes from the real
Pipeline into `dual_v4_planner`, rather than the old staged v3 planner. Profiles
explicitly declaring v3 retain their compatibility behavior; single-arm Atomic
v2 is unchanged. The pipeline must receive an adapter-owned ControlSkillContract
snapshot. Absent/unadvertised v4 is rejected without v3 fallback. No live adapter
is represented as advertising this capability by these changes.

The Qwen path receives the grounded task (including full placement/motion
semantics), bound operation IR, actual arm setup/runtime, Scene revision/digest
and registered skill contract. It emits only per-operation skill chains through
`plan_dual_operations`; it cannot change arms, operation coverage or scheduling.
Recipe mode requires an explicitly registered v4 recipe, not an implicit reuse
of old task-expansion rules. Control parameter schemas remain authoritative.

Registered skills additionally declare `object_parameters`, mapping parameter
names to bound source/destination/reference roles. `None` means that role metadata
is missing and cannot authorize v4 use; `{}` explicitly means an object-free
skill. The planner checks model parameters against the bound IDs before export.
This is an adapter contract requirement, not a claim that the current Control
repository already publishes it. Scene digests use the Gateway's canonical digest
function instead of the legacy execution-checkpoint serialization.

Arm resolution now receives runtime state. A held object remains with its actual
holder; an explicit conflicting arm request or duplicate holders is rejected.
Assignment decisions record explicit/held/configured-default/balanced-fallback
provenance in the planner trace. The existing deterministic fallback policy is
retained; evidence-based Qwen arm assignment is not yet wired into this path.

For a shared destination across arms, Python derives one exclusive resource ID
and per-operation placement intervals from the first skill whose registered
object parameter identifies the destination through the remainder of that chain.
No arbitrary cross-arm order is added. Explicit required parallel groups create
sync groups on operation starts; ordinary independent tasks do not. Both features
require advertised Control support. DAG validation rejects same-arm sync,
dependency-conflicting sync, duplicate group identities, and simultaneous starts
that compete for the same exclusive resource. Hold-event anchors remain incomplete
and hold requests are still explicitly rejected rather than dropped.

Pipeline/session tests cover v4 export, no-contract refusal, changed model object
binding, the actual mocked Qwen request builder and held-object continuity.
Additional planner tests cover shared-container resources, explicit start sync and
unadvertised-feature refusal. These are planning tests; `mark_dispatched` still
refuses v4 pending the real adapter/result contract, and the public Web dual gate
has not been loosened. No physical execution or live browser success is claimed.

Latest validation after the v4 Pipeline changes: Python 3.12 full suite
**1677 passed, 31 skipped** (34.36 s); Python 3.11 targeted dual assignment,
v3/v4 pipeline, resource/sync and DAG regression **35 passed** (0.20 s).
Schema drift and whitespace checks pass. This latest Python 3.11 run is targeted,
not a replacement claim for a full-suite run on these final edits.

## Hold-event anchors connected to v4 planning

The previous unconditional hold rejection in `dual_v4_planner` is replaced by
`apply_hold_constraints`. Registered skills supply explicit acquire/preserve/release
effects, and acquisition parameter roles must be in the trusted object-binding
map. No inference from skill names or simulated positions is used.

The planner anchors to verified input holding state or a preceding holder chain's
registered effects. Region-qualified milestones preserve the bound region ID.
The other operation waits for the establishment anchor; the holder's next command
waits for the other operation's completion. The existing graph validator rejects
cycles or incompatible sync rather than dropping constraints. A conflicting
acquisition by the other arm is refused. No wait/no-op skills are added, and the
planned effects never update real runtime state. Missing Control hold support or
effect metadata still fails explicitly.

Public v4 schema now includes optional hold establishment and region fields and
has been regenerated from Python. Eight tests cover acquisition/release anchors,
initial holding, region milestones, missing support/effects, wrong held identity,
dependency cycles, and export through the actual session/Pipeline with unchanged
runtime state. Python 3.12 full regression after the implementation: **1684 passed,
31 skipped** (34.87 s); the additional session/Pipeline test was added afterwards
and passed in the **8-test** hold run. Python 3.11 combined v4 regression including
that test: **40 passed**. This does not establish live Control execution of hold
events; adapter negotiation and event/result protocol acceptance remain pending.

## Visual assignment integrated before v4 skill planning

`ArmAssignmentRequest` carries bound operation/object identities, locked arms,
actual profile arm labels, runtime holdings and a revision-bound camera frame.
`QwenHTTPProvider.assign_arms` uses the dedicated assignment prompt/schema and
an image request, not the skill planner prompt. The main v4 Pipeline passes its
capture callback to the resolver only when assignment is needed; fully locked
tasks skip both capture and the model. Existing v3 compatibility is unchanged.

Before a model call, the resolver validates Scene ID/version/sub-version, known
unique frame instance IDs and presence of both arm identities plus operation
sources. Image position is never substituted for robot arm identity. A malformed
assignment, changed lock, lost operation, changed same-object continuity or order
fails rather than being overwritten. Explicit insufficient evidence is recorded
as such; configured/balanced deterministic fallback is separately attributed.
No-response/transport errors are not hidden by fallback.

Ten tests exercise the actual mocked HTTP request shape, partial locks, no-call
fully locked behavior, each stale revision component, insufficient-evidence
provenance, illegal lock changes, missing image arm identity, and session-level
assignment→v4 skill planning with preserved object IDs and unchanged runtime,
and actionable clarification when neither evidence nor a declared fallback exists.
These are not real-model visual quality tests. Python 3.11 assignment/v4 targeted
regression: **29 passed** (0.16 s). Live image/model acceptance remains outstanding.

## Latest verification checkpoint (2026-11-27)

Python 3.12 full suite on the current implementation: **1695 passed, 31 skipped**
(37.85 s), using `PYTHONPATH=. conda run -n robot_agent_integ pytest -q -o addopts='' --tb=short`.
Schema generation `--check` and `git diff --check` both pass.
Skipped tests are not treated as verified live integrations.

Read-only reinspection of local Control and bridge found no `commands_dag_v4`
capability advertisement or resource/hold/sync consumer. The bridge currently
forwards the command file through `link.control_child`; Control's
`demo/interaction/command_converter.py` converts a commands list into ordered
steps, and `demo/run_demo.py` iterates commands. These are not evidence of DAG
scheduling support. The existing v4 dispatch refusal remains necessary; do not
enable Web dual execution by silently converting the new protocol to this path.

Still outstanding: live Control negotiation/result acceptance, real Qwen and
browser acceptance, remaining layout region/spacing coverage, and final package
and cross-version release gates. No service restart, commit or push was performed
for this checkpoint. The overall implementation is **not yet complete**.
## Authorized automatic-spacing search checkpoint

The layout resolver now retries regular line/grid/checker/alternating candidates
only with explicit automatic-spacing authorization. Every candidate is isolated
and geometry-validated; count, region and pattern center remain fixed. Search is
bounded (48 candidates, 10% increments) and stops on capacity/support errors.
Fixed spacing and explicit radii are not changed. Actual accepted spacing and
attempt count are recorded in assumptions. This does not claim exhaustive search
or complete adaptive scatter/free-path layout support.

Three new regressions cover a centered obstacle requiring expansion, fixed
spacing refusing the same kind of collision, and insufficient region capacity
remaining atomic without reducing object count. Identical requests produce the
same patch and diagnostics; successful publication increments the version once.

Validation on these changes: Python 3.12 full suite **1698 passed, 31 skipped**
(34.43 s); Python 3.11 layout transaction/pattern suite **54 passed** (0.43 s).
Whitespace check passes. Live-model/browser and Control v4 gates remain open.
## Relative region implementation checkpoint

`relative` now resolves anchor world bounds and clips the tabletop by the
requested left/right/front/back side plus clearance. All member footprints must
fit this region; it is not a table-half shortcut. Missing direction is rejected
at contract validation. The U prompt documents the distinction; no world
coordinates or asset IDs are delegated to the model.

Seven tests were added: missing center/any direction, four directional footprint
and support checks, and side-capacity failure with unchanged input Scene.
Python 3.12 full suite: **1705 passed, 31 skipped** (34.74 s). Python 3.11 targeted
contract/transaction/route suite: **45 passed** (0.48 s). Schema drift and whitespace
checks pass. This remains local code verification, not live Qwen/browser proof.
## Cross-object same-arm constraint checkpoint

Added optional Operation/Full U `same_arm_group`, with frozen additive Compact
key `sg`. Parser expansion preserves the value, and assignment connects actor
identities transitively across groups. Explicit and verified held-object locks
propagate across each component; conflicting locks refuse before planning.
Model validation receives the full groups and cannot split them. Deterministic
fallback also locks a component at once; inherited assignments are auditable.
Downstream DAG uses the resulting locked arms rather than an invented skill or
barrier. Existing protocols without this optional field remain accepted.

Five regressions cover explicit-lock propagation without a model, explicit lock
conflict, forbidden model split, Full/Compact round trip, and transitive groups
with held-object ownership. Python 3.12 full regression: **1710 passed, 31 skipped**
(34.58 s). Python 3.11 assignment/v4 regression: **26 passed** (0.15 s).
Schema drift and whitespace checks pass. Real Control v4 dispatch remains gated.
## Real Qwen custom-path smoke (2026-11-27)

Ran the local Qwen3.8-27B Q4_K_M service through the production `plan_layout`
request/schema/parser. Added reproducible `scripts/smoke_layout_qwen.py`, which
saves raw values, full request schemas/prompts, call timing/token evidence and
normalized six-slot plans in unique directories. It never publishes a Scene or
calls Control; no hidden retry is performed.

First run `var/layout-dual-audit/qwen-path-20261127-01`: three protocol-valid
responses, but manual semantic inspection found V/Z used image-down coordinates
and would be inverted on the tabletop. This is NOT recorded as three semantic
successes. Clarified u-right/v-up convention in the custom-layout prompt.

Second run `.../qwen-path-20261127-02`: three protocol passes, all orientations
correct on manual inspection. Third independent run
`.../qwen-path-20261127-03`: added an independent line/V/Z orientation oracle;
all three pass both protocol and orientation checks. These cases do not establish
arbitrary free-pattern quality. Latest per-case input/output tokens and total
call seconds: line 260/29/0.804, V 262/46/1.182, Z 262/53/1.311. Requests reuse
the running service cache; this is not a cold-start benchmark.

Targeted smoke-oracle/provider tests: **6 passed** (0.06 s). The oracle explicitly
rejects the original inverted V/Z. Full-suite result above predates this prompt
change and new smoke test. U routing, footprint fitting of boundary path points,
real browser capture, and live dual Control remain separate outstanding gates.
## Free-path footprint fitting checkpoint

Real path output exposed a separate Resolver issue: coordinates at 0/1 were
mapped to the bare surface boundary, leaving member footprints outside it.
Custom/text/scatter now map to a common inset origin region computed from user
margins and rotated/scaled asset bounds. Shared insets preserve the pattern for
mixed assets; no per-object clamping, scale reduction or count change is used.
Follow-pattern yaw is computed after a conservative yaw-independent fit. Normal
support, capacity and collision checks still run on the final candidate.

Two regressions cover a complete 0→1 diagonal with fixed/follow-pattern headings,
all footprints within margins, unchanged input and one version increment.
Python 3.12 full regression: **1713 passed, 31 skipped** (34.93 s), including the
new live-smoke orientation oracle. Python 3.11 layout/path/font/provider subset:
**48 passed** (0.52 s). Schema drift and whitespace checks pass. This checkpoint
does not establish real browser or Control acceptance.
## Real Compact U layout routing checkpoint

`scripts/smoke_layout_understanding.py` loads the configured live OLS catalog and
calls production `BrainPipeline.understand_turn(scene=None)` only. No bootstrap,
Scene submission, browser mutation or Control call occurs. Evidence is stored in
`var/layout-dual-audit/qwen-u-20261127-01` and `...-02`.

First run: grid accepted, circle and alternating rejected. Raw outputs showed
missing mode with `auto=true`, and missing spacing plus missing item mode.
These are real wire-schema gaps, not OLS or geometric failures. Compact schema
now branches spacing/items by mode, requires the applicable values/sequence,
and preserves mode fields during encoding. Decode validates before walking the
canonical field schema; no inferred mode or arbitrary branch selection is used.
Full mode defaults are unchanged.

Second independent run: **3/3 route/type/count passes**, radius .2 and explicit
.1 center spacing preserved. However alternating also emitted irrelevant radius,
angle and text fields plus unrequested region dimensions. This remains a semantic
quality gap; do not describe this smoke as complete layout acceptance. The first
run grid also supplied an unrequested fixed spacing, so source attribution and
pattern-specific fields still need further work. Both raw runs are retained.

Added six negative schema regressions. An initial full test run used the wrong
exception class in those new assertions (six failures); after correcting the
tests to JSON Schema ValidationError, final Python 3.12 full regression is
**1719 passed, 31 skipped** (34.91 s). Python 3.11 routing/composite subset:
**13 passed** (0.31 s). Schema drift and whitespace checks pass.
## Pattern-specific wire grammar and live retest

Introduced shared `PATTERN_FIELDS`/`PATTERN_REQUIRED` policy. Python rejects
inactive nondefault parameters; Compact closed per-pattern branches prohibit
inactive fields entirely, including null. The codec remains schema-directed and
lossless, with no cleanup of malformed model output. Fixed an old ring test
fixture that supplied a redundant circle radius alongside inner/outer radii.

Real production U run `var/layout-dual-audit/qwen-u-20261127-03` passed all three
route/pattern/count checks without retries. Inspecting raw responses confirms the
alternating case no longer invents radius/angle/text/region dimensions and retains
the explicit .1 center spacing and alternating sequence. One remaining issue:
model-filled clearance differs from configured defaults without user evidence
(.02 for grid, 0 for alternating). Parameter provenance/default policy requires
further work; no complete semantic/browser acceptance is claimed.

Six new negative tests cover inactive canonical fields and Compact null/non-null
radius rejection on grid. Python 3.12 full suite: **1725 passed, 31 skipped**
(35.28 s). Python 3.11 contract/pattern/routing/composite subset: **49 passed**
(0.39 s). Schema drift and whitespace checks pass. No Scene or Control effect,
service restart, commit or push occurred.
## Cross-version full regression and installed wheel checkpoint

Current source full suite on Python 3.11: **1725 passed, 31 skipped** (30.16 s).
The matching Python 3.12 full result is **1725 passed, 31 skipped** (35.28 s).
Neither counts skipped integration tests as passed.

Rebuilt wheel in `/tmp/brain-layout-release-azkawG/dist/` with isolated hatchling
1.33.0; SHA256:
`f906c8f515de6d16a1b8ce3a847112b28afa2237e98d1ee69f97916114318f5e`.
Installed into separate Python 3.12 and 3.11 environments, ran outside checkout:
`scripts/wheel_smoke.py` and `scripts/wheel_understanding_smoke.py` both pass.
The environments resolved pydantic 2.14.4, httpx 0.29.0, jsonschema 4.26.0 and
web/batch/layout extras independently of the development environment.

Extended wheel smoke checks all four packaged public layout/DAG schemas against
installed models, layout and assignment prompts, deterministic grid generation,
Compact layout round trip, offline CLI/replay and Web route imports. The old smoke
initially failed because it expected default recipe planning and validated Atomic
commands against the legacy schema. Updated the test to assert production Qwen
default, explicitly select recipe for offline replay and validate Atomic output;
no production behavior was changed to satisfy those outdated expectations.

Passing wheel-smoke artifact directories:
`/tmp/brain-wheel-smoke-3_gjmrot` (3.12),
`/tmp/brain-wheel-smoke-37_0r11v` (3.11).
These are local temporary build/test artifacts, not a published release or a
deployment. No service restart, Control execution, commit or push occurred.
## Real OLS candidate replay checkpoint

Added `scripts/audit_layout_candidates.py`. It replays captured canonical U
output against the configured OLS default Scene using application editor/default
policies, checking the source catalog revision first. This is a private candidate
test, not a Gateway transaction or a genuinely empty-session bootstrap test.

`var/layout-dual-audit/candidates-20261127-01`: all three live-U layouts produced
valid candidates (6 grid apples, 5 circle apples, 3+3 alternating fruit), each from
the same unchanged default Scene, each with exactly one private version increment.
Saved before/candidate Scene, patch, IDs and digests. During evidence review,
found radial layouts misleadingly reported unused spacing; changed diagnostics
to actual radius for round patterns and actual origin bounds for free paths.
`.../candidates-20261127-02` repeats all three successfully with corrected logs.

Python 3.12 full regression: **1725 passed, 31 skipped** (34.90 s).
Python 3.11 layout transaction regression: **38 passed** (0.43 s).
Whitespace check passes. Earlier wheel checkpoint predates this diagnostic-only
resolver adjustment. Remaining gates include provenance of model-supplied layout
defaults, actual empty-session/browser publication, and negotiated Control v4.

## Real empty-browser bootstrap checkpoint (2026-11-27)

Started isolated Gateway 8096 / Brain 8503 with separate state and task directories
under `var/layout-dual-audit/web-20261127-01`. Production 8099/8500 was not
restarted or used for scene writes. Control execution is disabled in the isolated
Brain. Logged in through the real browser and submitted the same six-apple,
two-row/three-column request in three independent initially empty sessions.

First results (not hidden by retries):

1. `fa292c798b3a43eaa8f565738dc837a5`: `scene_patch_scene_mismatch`.
   The layout bootstrap copied the typed template identity but retained the
   old private raw document. Fixed by reparsing an updated lossless document.
2. `603d004aee2c46a288637a00a2717df0`: `validation_failed` on OLS
   `scene_name_Chinese`. Fixed bootstrap normalization to use the shared lossless
   parser. A regression then exposed the same closed-schema assumption during
   artifact publication; publication now validates the decoded typed Scene and
   preserves/round-trips the full document. Invalid objects remain rejected.
3. `8721348e335d465f8558ff4e25d5fbc2`: `gateway_commit_readback_mismatch`.
   The live browser has 14 objects (8 platform + 6 apples), but the exact
   candidate/readback diff is `/scene_name_Chinese`: submitted `空场景`, absent
   in readback. Transaction remains unknown; this is **not an accepted pass**.
   Do not remove digest checking or repeat the task in this uncertain session.
   Browser serialization metadata preservation is the next integration issue.

All model responses, tracebacks, transaction request/receipt and live scene are
retained in that directory. Camera capture returned `scene_lease_required` and
is explicitly recorded as blocked, not replaced with a fake success image.

Tests now cover parsed/file-backed templates as well as synthetic SceneConfig,
including nondefault template identity and OLS display metadata. Latest Python
3.12 full regression: **1727 passed, 31 skipped** (35.20 s). Focused bootstrap
and artifact regressions: **11 passed**. No commits/pushes or Control execution.
The latest fixes still require Python 3.11 and wheel revalidation. Browser
bootstrap, remaining layout semantics and Control v4 are not fully accepted.

## Browser metadata fix and successful bootstrap (2026-11-27)

The frontend `editor/src/world.ts` reconstructed only known top-level fields,
silently dropping OLS `scene_name_Chinese`. Added isolated opaque document metadata
storage: load/export retain it, accepted world replacement replaces it, rejected
atomic candidates leave it unchanged, and nested input/output objects cannot
mutate the stored values. Core metadata and object fields remain authoritative.
No digest checks were removed. Frontend changes are uncommitted in the existing
`web-frontend-master` checkout; unrelated untracked certificate files untouched.

Frontend checks: TypeScript passes; **786 tests pass**; production-format Vite
build succeeds to `/tmp/layout-frontend-build-20261127` (existing large-chunk
warning). Production `dist/`, Gateway 8099 and Brain 8500 are unchanged. Used
development frontend 5176 proxying isolated Gateway 8096 / Brain 8503.

New empty session `0e81c656aaf642b1a026df9fa41d3422`:

- Layout task `2c1d558a5e0e4d639f64cc529100b24f`: real Qwen + browser commit
  succeeds, six apples, three X positions/two Y positions, scene version 1.
  Live readback equals published Scene digest. Camera 5 capture is a validated
  640×480 RGBD PNG; visual inspection confirms two rows of three apples.
- Query task `3c92d21fadca4c2497d4655fc9cba171`: reply `匹配对象共 6 个。`;
  complete before/after Scene and digest are identical, version remains 1.

Evidence in `var/layout-dual-audit/web-20261127-01/`:
`grid-browser-success.json`, `grid-browser-success.png`,
`query-continuity.json`, plus both task directories and transaction receipts.
Screenshot capture used a separately acquired/released audit lease, without
changing Scene. Its first attempt used a string taskID and was rejected as an
invalid parameter before acquisition; the corrected integer request succeeded.
The three earlier failures remain separate evidence, not overwritten by this pass.

This proves one real grid bootstrap and its query continuation, not the full
layout/composite/dual-arm acceptance matrix. Control remains execution-disabled.
Gateway Python regression (`python -m pytest`): **545 passed**, 35 warnings,
29.96 s. A first invocation via the `pytest` console entry failed collection
because the repository root was absent from its import path; the module entry
resolved it without changing code or tests.

## Automatic circle radius checkpoint (2026-11-27)

Addressed the L02 contract gap: `circle.radius_m` may be omitted only when
`spacing.mode=auto` and `auto=true`; fixed-spacing input without radius still
fails. No new model-generated coordinate or physical parameter is introduced.
Canonical and Compact pattern schemas share this policy; schema exports regenerated.

The Resolver derives a conservative initial radius from transformed footprint
corners and requested count (chord separation), including non-centred origins.
Around/near an anchor additionally reserves its bounded footprint. Authorized
collision-only retries expand radius with the existing bounded candidate search.
Each trial preserves exact count and goes through normal region, support and
collision checks. Capacity failure does not silently reduce count or shrink the
assets. Explicit radius is never adjusted. Diagnostics record actual radius and
search attempts. This bounded search is not a proof of all possible packings.

Added one/two/five/eight-member deterministic tests, absent authorization rejection
and exact-count capacity failure. Python 3.12 full: **1733 passed, 31 skipped**
(37.76 s); Python 3.11 focused: **60 passed** (0.56 s).

Real Qwen evidence `var/layout-dual-audit/qwen-u-auto-circle-20261127-01`:
four cases passed route/count checks; fourth also checks omitted radius and
explicit auto mode. Its instruction explicitly requested automatic radius.
Private OLS candidate audit `auto-circle-candidates-20261127-01` passed four
cases without publishing or Control calls. Five apples used derived radius
0.10717057039835348 m, first candidate accepted. This is not browser publication
evidence; isolated running Brain has not yet been restarted with this increment.

Second real run `qwen-u-auto-circle-20261127-02` removed the explicit automatic
radius wording: `在桌面新增五个苹果，均匀围成一圈`. All four smoke cases and all
four private candidates passed. The new fourth response omits radius and uses
auto spacing, without a repair retry. It used one U call (17,965 input / 235
output tokens, 6.318 s); server reported 17,681 cached input tokens, so this is
warm-cache evidence, not a cold performance comparison. Known circle planning
and geometry required no additional model call. Schema drift and whitespace
checks pass.

## Multi-turn arrangement understanding checkpoint (2026-11-27)

Found that persisted arrangement records were never supplied to U. Added a
read-only, current-scene-scoped membership context (group ID, slot/member IDs,
asset aliases and missing-member flags; no world poses). Normal, composite and
failure-preview entry points receive the session's index explicitly; no shared
pipeline field carries another session's index. Execution still validates the
index, object existence and scene identity independently. Mutating the context
cannot mutate the durable index. Other-scene records are excluded.

Real saved-scene follow-up run `qwen-followup-20261127-02` exposed a second issue:
U correctly chose `arr-1` for a rearrangement but omitted `operation`, defaulting
to create. Existing duplicate-group checks prevented execution. Compact now
requires an explicit arrangement operation (including create), with a regression
that removing it rejects the response. Full historical defaults remain unchanged.
Prompt describes create/append/rearrange/replace semantics rather than rewriting
the model's output after the fact.

`scripts/smoke_layout_followup.py` provides a repeatable, no-side-effect real-U
test against saved scene/index evidence. Run `qwen-followup-20261127-03` passes:

- New five bananas, right-half automatic circle: new group ID, correct asset,
  exact count/region/pattern and no invented fixed radius.
- Rearrange the existing six apples into a line, 10 cm center spacing: original
  group ID, explicit rearrange, unchanged requested member count.

Both canonical responses passed private OLS candidate resolution. The rearrange
candidate retained all original IDs and all nonmember objects unchanged; each
candidate increments its private version once. No Gateway publish or Control
call occurred in these follow-up tests. Prior browser success is not reused as
evidence that these new follow-ups have been published.

Python 3.11 focused context/wire tests: **13 passed**. First full regression
revealed five legacy preview fixtures lacking the optional index attribute;
read-only preview now accepts an absent index as empty context. That intermediate
full gate passed **1735 tests, 31 skipped**; latest operation-required gate is
recorded separately after completion. An initial diagnostic launch with rendering
enabled stopped before Qwen; the reusable script explicitly disables rendering
and execution for this read-only audit.

Latest Python 3.12 full gate, including required Compact operation:
**1736 passed, 31 skipped** (35.21 s). Schema-export and whitespace checks pass.
Production and isolated running services have not yet loaded this latest change;
browser follow-up publication and fresh wheel validation remain open.

### Restart checkpoint correction (2026-11-27)

After restarting only the isolated Brain with the latest follow-up changes,
the existing browser session `0e81c656aaf642b1a026df9fa41d3422` rejected a
rearrange request with `browser_scene_version_conflict`. The checkpoint had
lost `scene_name_Chinese`, while the browser retained it. This was a persistence
defect, not permission to relax the version/digest gate.

SessionState now serializes the lossless Scene document and validates it through
the shared document parser on load. Rejected objects still reject the checkpoint;
save readback explicitly checks raw-document equality in addition to typed state
consistency. Tests cover omitted/zero/nonzero sub-version, nested document
metadata, two save/load cycles and duplicate-object rejection. Focused checkpoint
tests: **32 passed**. Existing damaged historical checkpoints were not rewritten.
Full regression: **1740 passed, 31 skipped** (35.31 s); whitespace checks pass.
Fresh-session browser restart validation remains pending. This checkpoint fix
has not yet been loaded into the isolated running Brain; production is unchanged.

### Browser restart and composite evidence (2026-11-27)

The checkpoint fix was loaded into isolated Brain 8503 (Gateway 8096 / Vite
5176). Production services and Control were not restarted or called.

- Session `5f799f83b8a44c989b4eb0fbd0294da7`: real empty-scene creation of five
  apples in an automatic circle succeeded. Gateway capture and saved checkpoint
  match the published lossless Scene. Brain was then stopped while idle and
  restarted with the same checkpoint. Rearranging those apples into a line with
  10 cm center spacing succeeded. IDs 8–12 and all nonmembers are unchanged;
  Scene version changes exactly 1 → 2. Evidence is under
  `var/layout-dual-audit/web-20261127-01/{circle-browser-success,restart-rearrange-browser-success}`.
- Session `8e693fefcddc489d980a24a2aab7a629`: one real composite understanding
  call (18,287 input / 424 output tokens), followed by one skill planner call
  (4,215 / 83), created two apples then planned a grasp of the leftmost new
  apple. No second U, vision or layout-model call occurred. Browser displayed
  "计划已生成，尚未执行". Layout and robot phase use the same new version/digest.
  However the exported Atomic document lacked its own digest, so this run is
  evidence of phase continuity, not full command-binding acceptance.
- Session `c6732c8532f2460897ea3ff184efddc0`: two apples were committed, then
  grasping missing banana stopped with `grounding_missing`. Browser retains the
  committed two-apple scene, verified by Gateway capture. No banana was created
  and no robot Commands were produced. Evidence: `composite-missing-target-*`.

The missing exported fingerprint is now fixed: optional historical
`scene_digest` fields in legacy/Atomic v2 and staged v3, stamped from the current
lossless Scene at live session export. Existing mismatched version/digest is
rejected rather than rewritten. v4 retains its required digest. Historical
documents without the field still round-trip without adding it. Composite
validation now requires digest equality. This is transport metadata, not a new
model-output field or Control skill.

New tests assert exported digest, reject stale version/digest without mutating
export state, and preserve historical command replay. Python 3.12 full gate:
**1743 passed, 31 skipped** (35.71 s). A new real browser run for this final
binding change is in progress; do not treat the earlier run as its evidence.

Before the digest change, Python 3.11 full gate passed **1740 / 31 skipped**;
the rebuilt wheel `f2a664237eaee44046113b1b4031bc62587335c0eea5e06c6eecabaee5d19ded`
passed both offline smoke scripts on separately installed 3.11 and 3.12
environments outside checkout. That wheel predates the digest fields and is not
the final release artifact.

Final digest-binding browser rerun: session
`860a1b1a8d9d414f9d60f30d8addbe8f`, Commands request
`6dce61881384437f9412c5d8396350e9`. One composite U and one skill call,
layout committed before planning, and exported `scene_digest` equals the
committed scene, phase ledger and Gateway capture:
`237784d3170913a4c182b6cc0cabef99992fc8da9b3d4c9b0d0ba0f715890784`.
Evidence: `composite-digest-verification/` and `composite-digest-capture/`
under the same isolated audit root. This is real model/browser **planning**
acceptance, not Control execution or dual-arm DAG runtime acceptance.

Post-change Python 3.11 full gate: **1743 passed, 31 skipped** (30.04 s).
Latest wheel SHA256:
`271eed143c3c287abff0c702e185540166a974cd752f0ae6a13a7c09aaff7d37`,
at `/tmp/brain-layout-digest-release-20261127/dist/`; both installed-wheel smoke
scripts pass outside checkout on 3.11 and 3.12. Smoke outputs:
`/tmp/brain-wheel-smoke-57dlrk77` and `/tmp/brain-wheel-smoke-9udd10ad`.
Remaining scope still includes failed-layout ID reservations, remaining
original/incremental layout boundaries and full requirements/Control capability
audit; these passing gates do not establish completion of the attachment.

### Failed-layout identity reservations (2026-11-27)

Attachment §5.2 requires failed reserved IDs not to be reused. Two prior tests
incorrectly expected a layout failure to leave the allocator unchanged. Updated
that expectation, not the scene rollback guarantees.

The session's existing allocator now reserves one bounded range after layout
planning/reference validation and before candidate construction for
create/append/replace. Rearrange does not allocate. All authorized automatic
spacing/radius trials share the same range. The application checkpoints the
high-water mark and `layout_id_reservations` before the resolver runs; failed
checkpoint writes stop before candidate construction. This is internal session
metadata, not a new Scene v1 attribute or another instance allocator.

After success or failure the reserved range joins identity history. Restore
also retires saved ranges, including a process loss before the final checkpoint.
Scene contents, digest, version, original and arrangement membership still
roll back on layout/commit refusal. A previously successful request reuses its
existing receipt. A reserved request with no success receipt returns
`scene_layout_request_reserved`, rather than constructing the same transient IDs
again; callers must reconcile publication before starting a new request.

Coverage added for a checkpoint observed before candidate failure, restoring
without a post-error save, new-request allocation above failed IDs, failed empty
bootstrap followed by application restart, unavailable checkpoint storage,
Gateway commit rejection, and malformed/overlapping reservation ranges. The
range length is bounded at the contract's maximum 1000 slots before restore
expansion. Original/current/replace failures now verify allocator advancement
while retaining scene rollback. Initial focused gate: **66 passed**; expanded
Python 3.11/3.12 full gates both pass: **1753 passed, 31 skipped**
(30.44 s / 35.55 s). Schema drift and whitespace checks pass. Running services
have not loaded this change; latest installed wheel predates these reservations.

Follow-up audit found an additional routing gap: the resolver and its direct
geometry tests support `region.kind=relative`, but `BrainPipeline.process_turn`
still rejects that kind before calling the resolver. This needs an end-to-end
pipeline regression, not another resolver-only test, in the next checkpoint.

### Relative-region main-path correction (2026-11-27)

Removed the obsolete pipeline rejection of the contract/resolver-supported
`relative` region. Before allocating candidate IDs, the pipeline now resolves
both the support surface and the anchor (rather than only the anchor for
non-surface regions). Missing support or anchor returns
`scene_layout_region_unresolved`; no IDs or scene objects are allocated.

`brain_tests/test_layout_relative_session.py` exercises the complete
BrainSession → BrainPipeline → resolver → platform commit path, without a
model provider: all four directions, actual AABB clearance, support footprint,
unchanged anchor/platform objects, exact count, one version increment, receipt
replay, missing anchor/surface and capacity rollback. Seven new cases pass;
combined layout route/transaction gate **62 passed**. Python 3.11 focused gate
**27 passed**. Python 3.12 full gate **1760 passed, 31 skipped** (35.71 s).

Loaded reservations and this correction only into isolated Brain 8503 after
verifying it idle. Real browser anchor setup succeeded; the relative-layout
request is under test. Production services and Control remain untouched.

The first real relative-layout test was **not semantically correct**, despite a
successful Scene commit/capture. Session `eb4c03d24a514d39adabb3eb59de7f0f`, task
`ef951b3610ce4321866517712b2bb607`: Qwen supplied `anchor_ref=basket` but omitted
region kind, which defaulted to `surface_region` and ignored the anchor.
The evidence directory `relative-browser-success` keeps its original capture
name but now contains `semantic_verification.json` explicitly marking failure.
It must not be counted as a passing relative-layout case.

Corrective contract/wire change: canonical `surface_region` forbids a non-null
anchor; Compact requires explicit region kind and uses closed kind-specific
branches. Anchored kinds require a reference; relative also requires an explicit
direction and cannot select center/any. No field is deleted or inferred to make
an invalid model response pass. Added invalid/valid wire and canonical cases;
focused gate **36 passed**. Fresh-session real-Qwen rerun and full regression are
pending for this stricter schema.

Strict-schema real rerun passed, session `fafd8b61996d4a789d1ecea0d65029f0`,
task `5cc5bc08184646cda0096346a2c25a0d`: exact same instruction now explicitly
returns `relative`, anchor `basket`, right-half direction, two apples, Y-axis
line and automatic spacing. One U call, no layout-model call or retry. Actual
apple AABBs are strictly to the right of the basket AABB plus required clearance;
both support footprints fit. Nonmembers unchanged, version 1 → 2, reserved IDs
16–17 are the final members. Gateway capture matches published Scene digest
`4b5cbdd002b43af0b79c7c9cab0d8b00a38e7001cd92b0f26b285e30e574217e`.
Evidence: `relative-strict-browser-success/{capture,semantic_verification}.json`
and `screenshot.png`. First failed semantic run remains in the report.

Python 3.12 full gate after strict-region change: **1767 passed, 31 skipped**
(36.09 s). Production and Control remain untouched. Latest wheel still predates
the reservations/relative-region changes and needs rebuilding before release.

## Original arrangement continuity (2026-11-27)

Original manifests now freeze arrangement membership when the original Scene is
captured. Loading and prepared-write recovery validate member identity against
that immutable Scene. Legacy manifests remain readable with no fabricated groups.
Original append/rearrange/replace resolve against frozen membership, not the
current branch. Derivation remaps retained groups to fresh object IDs after the
platform accepts the transaction. Original Scene and manifest bytes remain
unchanged. A current-only group cannot be used as an original group.

Regression exposed a separate loss of top-level display metadata in component
reference validation. Reference validation and ID remapping now preserve the
lossless Scene document while still validating typed fields and references.
Removed the temporary blanket rejection of original append now that frozen
membership is available. Four new continuity tests pass, including restart,
divergent current layout, fresh IDs and immutable original files.

Python 3.12 full gate: **1771 passed, 31 skipped** (36.10 s).
These original-continuity changes are code-tested, not yet loaded into the
isolated browser service or verified through real Qwen. Original arrangement
context exposure to U, remaining P0–P7 acceptance, and rebuilding the release
wheel remain outstanding. Production services and Control are unchanged.

### Original context delivered to U

Added a read-only, hash-validated `original_snapshot` context separate from current
objects and arrangements. Normal U, composite U and failure-chain preparse receive
this per-session snapshot; recursive initial-robot parsing preserves it. The
provider cannot mutate the frozen snapshot through its request, and a subsequent
request without original context does not inherit it. Prompt basis authorization
remains explicit; exposing the snapshot does not authorize original edits.

Regression: Python 3.12 **1772 passed, 31 skipped** (36.21 s); Python 3.11 focused
context/original/recovery/composite suite **74 passed**. Five older recovery test
doubles were updated to implement the new read-only session method; their behavior
assertions were retained. `git diff --check` passed. Real-Qwen/browser validation
and the remaining release gates are still outstanding; no service was restarted.

### Refreshed installed-wheel gate

Latest Python 3.11 full suite: **1772 passed, 31 skipped** (30.97 s), matching
the Python 3.12 count. Generated public schemas pass the source consistency check.
Built the current worktree with isolated `uv build` (the application environment
does not contain hatchling, so direct no-build-isolation pip was not usable).

Wheel: `/tmp/brain-layout-original-release-20261127/dist/robot_agent_brain-0.1.0-py3-none-any.whl`
SHA256: `04644234bef5e8c9e5a038970536d3e161f6d4a777ec7360624f486928737a3b`.
Installed without dependencies into the dedicated 3.12 and 3.11 release test
environments. Both `wheel_smoke.py` and `wheel_understanding_smoke.py` passed
outside the checkout on both versions. This checks packaged schema identity,
layout planning, Compact expansion, replay, prompts, and Web imports/routes.
Replay evidence: `/tmp/brain-wheel-smoke-aumiph2_` (3.12) and
`/tmp/brain-wheel-smoke-lbbiwtb0` (3.11).

This is packaging/offline evidence, not real-Qwen or dual-arm execution evidence.
Original-context real-browser acceptance and the complete requirement audit are
still pending. No production install, service restart, commit or push occurred.

### Current layout after execution feedback

Audited the feedback-to-layout path. Append already recomputes retained members'
world positions from the current Scene, not cached arrangement coordinates.
However, single/dual feedback and reconciliation revalidation discarded lossless
top-level Scene metadata. They now share a codec-based validator preserving the
raw document and validating current typed values, including model-copy updates.

New simulated-feedback regressions confirm a moved layout member keeps its actual
position during subsequent append and the updated membership records that position.
A removed member makes append fail before allocating IDs, without changing Scene.
This does not claim real Control execution. Python 3.12 full suite: **1774 passed,
31 skipped** (36.36 s); Python 3.11 feedback/dual-recovery/session subset:
**44 passed**. Diff whitespace check passed. The packaged wheel above predates this
feedback fix; final release must rebuild it. Runtime services remain unchanged.

### Real U original/current contrast

Extended `scripts/smoke_layout_followup.py --original-context-fixture` to provide
explicitly labelled synthetic branch contexts based on a saved six-apple Scene.
This is read-only real-Qwen understanding, not a live session edit. First run
`var/layout-dual-audit/qwen-original-context-20261127-01` exposed a semantic failure:
original group `arr-1` selected but basis omitted, silently defaulting to current.
The current-branch contrast passed. Both raw responses remain preserved.

Compact now requires explicit arrangement basis, and encode preserves even the
current default. No Python inference corrects an invalid response. Full historical
input retains its previous default behavior. Regression covers both cases.
Fresh run `var/layout-dual-audit/qwen-original-context-20261127-02` passed both
original/arr-1 and current/arr-current-fixture with one U call each, no retry.
Requests, raw responses, canonical payloads and contexts are saved there.

Full Python 3.12: **1775 passed, 31 skipped** (36.48 s). Python 3.11 focused
route/original continuity: **24 passed**. Browser publication is still pending;
no services or production configuration changed and no Control was invoked.

### Live original branch acceptance and explicit spacing failure

Restarted only isolated Brain 8503 (PID 3376650), with Control disabled and no
active task; production untouched. Browser session `1caaf077fc72433c96e91bd19f9df6ac`:
initial layout `9c34cd29dbee451190babd42784b6277` created two apples but **failed
semantic spacing acceptance**: requested center spacing 20 cm, model returned
auto, actual spacing 0.094732012 m. Original raw response is retained.

Added `planning/layout_constraints.py`: explicit numeric center-distance phrases
are checked against spacing mode/value before layout planning or ID reservation.
Mismatch rejects, never silently repairs model output. Five tests cover metric
units, English expression, auto/wrong numeric response, no publication/allocation.
This bounded guard does not yet cover every numeric language form and has not
been loaded into the running isolated service. Python 3.12 full regression:
**1780 passed, 31 skipped** (36.63 s).

Separately tested original continuity despite the retained initial spacing defect:
task `0acc767a30a3449fa0afb6c4ef1f3c52` colored both current apples blue;
task `6f1c5dae37444a00912d22b00a0bf9bf` rearranged original apples along Y.
Derived apples are original red, IDs 26/27 instead of 8/9, new scene 3986130165,
version 1. Original file hash matches immutable manifest. Bound camera remapped
from 5 to 24; initial capture using old default failed CAMERA_NOT_FOUND and was
not reused. Successful capture uses session's confirmed camera 24.
Evidence `original-browser-derived-bound-camera/{capture,verification}.json` and
`screenshot.png`; capture digest matches publication:
`a18d62999752677ce6f141e1eefe07ce20384e86952365f6e857923461cf2a3f`.
This proves original branch publication/visual continuity, not exact-spacing
compliance or Control execution. Remaining gates and spacing follow-up remain open.

### Explicit spacing understanding follow-up

Added a concise center-spacing unit example to U and a read-only
`--explicit-spacing-fixture` mode in the follow-up smoke script. Real Qwen now
returns center/0.2m/auto=false for both the exact prior Arabic-numeric instruction
and its Chinese `二十厘米` variant, one call each, no retry. Evidence:
`var/layout-dual-audit/qwen-explicit-spacing-20261127-01`.
This proves only those two understanding samples, not general language stability.

The numeric consistency guard now supports common Chinese integers through 99;
unsupported/invalid matched notation produces an explicit error, not a guessed
distance or ignored constraint. Full Python 3.12 **1782 passed, 31 skipped**
(35.97 s); Python 3.11 spacing/layout/bootstrap **56 passed**. Diff check clean.
Live geometric spacing rerun, broader numeric provenance and final release remain
pending. No service restart or Control call this turn.

### Exact spacing real browser acceptance

Loaded the spacing guard/Prompt only into idle isolated Brain 8503 (PID3379301,
log `brain-spacing-01.log`). Fresh browser session
`0f1d42af79374af3a6425e700c62edb8`, task `bb94aacb28d24c8eba68ca265f2142f3`,
repeated the exact original instruction asking for two apples at 20 cm centers.
Published world positions are (-0.1,0,0.637373223) and (0.1,0,0.637373223),
distance **0.2m**, new scene version 1. Browser shows success; actual RGB capture
was visually inspected. Evidence `explicit-spacing-browser-success` includes
Scene, capture metadata, screenshot and numeric verification. Digest:
`9c37cbc8cc4a9722b8feb3c2b48ce5959c71f6ec3a93abbbf9436838e30c4f61`.
The earlier wrong-spacing result remains recorded separately.

Capture helper now reads the session-bound camera instead of default ID 5;
explicit `--camera-id` asserts that binding rather than selecting another camera.
Missing/mismatched binding fails before lease acquisition. This browser capture
used bound camera 5. No Control invocation, production restart, commit or push.
This closes the specific real-browser spacing rerun, not all P0–P7 gates.

### L03 alternating mixed assets live acceptance

Fresh isolated browser session `6410af15884b4460859c7d8dce5a9f12`, task
`88f7e46c18ac4aa9a6df711bba7b43f0`: three apples plus three bananas, left-to-right
alternating, 15 cm center spacing. Verified actual Scene identities in order
apple/banana/apple/banana/apple/banana, IDs8–13, all five tabletop XY gaps 0.15m.
Heights are separately derived from asset support geometry (apple Z0.637373223,
banana Z0.617377152); the tabletop spacing assertion is not a 3D origin-distance
assertion. Initial verification used 3D distance and was corrected to the specified
2D layout contract, without changing any generated Scene.

Single Scene version1, one real U call (18246 input /323 output tokens, 8.306s),
zero extra layout model calls, no Control. Capture visually inspected; evidence
`alternating-browser-success/{capture,verification}.json` and `screenshot.png`.
Published digest `ae1e98bca665aa5aeef79fbf090bd070d8a878f41c292a27afaf8d03c6db8707`.
No implementation/service changes this turn. Other unverified acceptance rows
remain open; this does not establish automatic-count adaptation coverage.

### Strict quantity boundary

Found canonical layout quantities accepted Pydantic coercion (boolean/string/
integral float into integer). Rows, cols, per-asset count and requested_count now
require actual integers; auto_count authorization requires an actual boolean.
Scope is the new Arrangement contract only, not legacy SceneEdit or robot tasks.
Added 24 invalid-value cases; contract suite 35 passed. Generated schema check
still passes (the public JSON types were already integer/boolean).
Python 3.12 full **1806 passed, 31 skipped** (36.60 s); Python 3.11
contract/route/transaction **98 passed**. No runtime restart or packaging rebuild;
latest isolated service and wheel predate this strict-type change.

### Count-only grid requirement restored

Attachment section3.3 explicitly permits grid rows/cols OR count. The deterministic
generator already supported deriving dimensions, but canonical and Compact gates
incorrectly required rows or cols. Removed that extra restriction from the shared
pattern rule. Total count remains required and exact; explicit rows×cols conflicts
still reject. Counts1/2/5/6/7/10 round-trip through Compact and generate deterministic
unique slots. A five-object resolver transaction creates five objects in a derived
2×3 grid, leaves the unused cell empty and increments the Scene once.

Seven new cases. Python3.12 full **1813 passed, 31 skipped** (36.78s);
Python3.11 pattern/transaction **74 passed**. Schema consistency and diff check
passed. This is not an automatic capacity-driven count reduction implementation.
Runtime/release wheel not updated; real count-only-grid U/browser remains pending.

### Reject contradictory auto spacing values

Resolver inspection found auto mode overwrote a supplied value_m. Canonical
ArrangementSpacing now rejects auto with non-null value_m; Compact's auto branch
permits only omitted/null value_m. Explicit center/edge values remain unchanged.
Regression verifies canonical and transport rejection instead of field deletion.
Python3.12 full **1814 passed,31 skipped** (36.31s); Python3.11
contract/route/transaction **100 passed**. Schema consistency/diff checks passed.
No service restart or wheel rebuild; real-browser pending gates remain unchanged.
# L04 around 独立浏览器复测（2026-11-27）

首次任务 d53f4099d70347c7a75ff77957818040 将“周围”错误解析为 relative/front_half，随后容量拒绝；不能将其认定为完整圆周真实容量不足。同会话重发进入失败恢复，未作为独立 U 修复验收。

补充 around/完整圆周的语义规则后，在新会话 d8b98d4d9e7e495ca6bd436fdf78941d 准备中央篮子，再执行“在篮子周围均匀摆8个苹果”。任务 29a23ee5966744eea6d50ceded25ad39 单次 U 成功，region=around/center，半径 0.28971470107919606 m，8 个实例角间隔 45°，已有对象不变，version 1→2。无控制执行。

证据：`var/layout-dual-audit/web-20261127-01/around-browser-success/` 包含 Gateway 真实截图、Scene、capture 与独立几何 verification。截图已查看，digest 与发布场景一致。此次仅证明一例修复后的首次调用通过；不覆盖模型稳定性、字体部署、双臂真实控制或完整交付验收。
# L05 字体真实链路（2026-11-27）

仅隔离配置注册系统 DejaVuSans，Brain8503 重启为 PID3387923，生产服务未动。新会话 81aa962e796c40f6b94ef69e263ff080 首轮“在桌面上用12个苹果摆成字母A，间距自动调整”，任务 75d04159715344b5b190f196bd13cff2 单次真实 U 返回 text/A、精确12、auto=true；Python 字体采样后由 Resolver 提交，version=1，未调用控制。保存的 arrangement 绑定 s0–s11 到 ID8–19，字体 SHA256 为 ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280。

证据：`var/layout-dual-audit/web-20261127-01/text-a-browser-success/`。Gateway 绑定相机5截图与发布 Scene digest 一致。已查看真实截图：12点字体轮廓稀疏，A的视觉辨识度有限，因此仅判定文字协议、确定性采样、真实发布链路通过，不把该截图作为优秀视觉效果或所有文字可用的证据。后续需要检查保持字体长宽比及轮廓表现，不能擅自增加数量或缩小资产。

字体读取改为一次字节快照同时计算哈希和采样，避免并发替换文件导致指纹与实际内容不同；缺失/损坏字体增加明确错误测试。Python3.11/3.12专项各6通过；最新3.12全量1816通过、31跳过（37.05秒）。3.11全量及最新wheel尚未复验。
# 文字比例修复与原样例重新判定（2026-11-27）

确认 Resolver 曾将字体 u/v 分别映射到矩形桌面两轴，导致字形拉伸。现仅对 text 使用 footprint-safe 范围内的等比正方形映射；custom/scatter 不变。补固定朝向与 follow_pattern 的真实 Resolver 仿射尺度回归，字体专项8项通过。

将上一轮真实 Qwen 的12苹果 A payload 原样离线重放到同一 OLS 默认场景，修复后返回 scene_layout_collision，证据 `var/layout-dual-audit/web-20261127-01/text-aspect-replay-01/report.json`。未调用模型、未发布 Scene、未调用控制。原浏览器“提交成功”不能作为修复后的 L05 成功验收：它依赖了拉伸，且视觉效果不佳。保留该失败，不减少数量、不缩小模型、不关闭碰撞。尚需验证合适资产/数量的等比文字布局与浏览器证据。
# 最新wheel独立安装验收（2026-11-27）

`uv build --wheel` 成功；产物 `/tmp/brain-layout-font-release-20261127/dist/robot_agent_brain-0.1.0-py3-none-any.whl`，SHA256 `3fe17853ea10523fe7d0b57add899e0dd131f7eb3ad5668c3263bab3c5609022`。包含字体快照与等比映射修复。

安装到已有隔离非editable Python3.12/3.11环境，工作目录 `/tmp`，分别执行 `scripts/wheel_smoke.py`、`scripts/wheel_understanding_smoke.py` 全部通过。前者确认安装模块位置、Schema与模型一致、Prompt/registry、CLI、Web路由和replay；后者使用MockTransport验证Compact解析。不代表真实Qwen、浏览器或控制执行验收。

逐次replay产物：3.12 `/tmp/brain-wheel-smoke-91t369fr`，3.11 `/tmp/brain-wheel-smoke-zejrlm8n`。源码schema生成一致性检查通过。最近源码全量3.12为1818通过/31跳过/36.96秒，3.11为1818通过/31跳过/31.26秒。完整附件验收仍有缺口，不进行完成声明或自动提交推送。
# L06 未声明数量真实U审计（2026-11-27）

新增只读 `smoke_layout_understanding.py --missing-count`，三条空桌面请求分别为苹果摆A、苹果围一圈、苹果香蕉交替。初次真实U结果0/3：第一条auto但无auto_count授权触发协议拒绝；第二条擅自默认1；第三条擅自默认3+3。证据 `var/layout-dual-audit/missing-count-20261127-01/`，无Scene发布/控制调用。

原因包括普通实体默认count=1与布局数量要求没有明确区分。补充布局语义：未给总数/资产数/行列数/既有组成员数且未明确授权自动数量时询问数量；自动间距不等于自动数量。独立真实U复测 `missing-count-20261127-02/` 为3/3明确澄清且无arrangement payload，无隐藏重试。55项契约/路由测试通过。该证据仅覆盖三例真实U，不能证明模型永不编造数量；全面数量来源约束与auto容量调整仍未完成。未重启服务，当前运行进程尚未加载本次Prompt修改。
# checker 精确数量规则统一（2026-11-27）

审计发现 `grid` 的显式 rows×cols 与 exact requested_count 冲突校验未覆盖 `checker`，导致2×3棋盘声明精确5个时只生成部分格子。现共用同一校验，5/7与2×3均拒绝；未声明行列、只给5个的棋盘仍输出精确5槽位并维持奇偶交替，不擅自补第6个。

新增4项显式尺寸冲突与1项count-only奇偶/数量测试，Python3.12/3.11契约、事务、路由各105通过。此修改不实现auto容量缩减，不把at_least或auto标签本身作为容量适配通过证据。原子提交与已预留ID规则未改变。
# 双臂真实U语义专项（2026-11-27）

`scripts/smoke_layout_understanding.py --dual-semantics` 新增三例无副作用审计，证据 `var/layout-dual-audit/dual-semantics-20261127-01/`。真实Qwen每例一次调用，3/3通过：左苹果/右香蕉、右苹果/左香蕉均保留正确grasp与显式arm；“同一只机械臂先抓苹果放下，再抓香蕉放下，不指定左右”生成依次grasp/release/grasp/release，四步同same_arm_group且arm均为空。已逐条检查原始canonical与binding_summary；没有因多个对象自动指定左右。

此为U语义证据，不是场景grounding、视觉自动分臂、DAG导出或Control执行证据。无场景发布、无控制调用。相关分臂/v4/视觉契约离线26项通过。自动数量容量调整仍未实现，不能将其安全拒绝计为已完成。
# 布局并发会话代码验收（2026-11-27）

新增 `test_layout_concurrent_sessions.py`，两个会话共享同一Pipeline和SceneEditor，使用Barrier保证同时进入布局候选解析，并故意复用相同request/arrangement名称。验证不同scene_id下2个X向与3个Y向对象的结果、版本、digest和成员记录隔离；第二会话容量失败时首个会话正常提交、失败会话不写场景/receipt；已成功请求重放不再次提交、不影响另一个会话。全程无Commands。

两项并发测试通过。此证据覆盖共享业务对象并发，不替代真实Gateway租约和浏览器发布隔离验收，后者仍待完成。
# 真实S发现v4隐藏串行屏障并修复（2026-11-27）

以明确标注的fixture-reviewed-v1测试契约调用真实Qwen S：一次调用，输入916/输出127 token，返回左右臂pick(source=7/8)正确。初次全链路断言失败，证据 `var/layout-dual-audit/dual-real-s-fixture-20261127-01/`，不是模型错误：TaskExpander旧逻辑在进入DAG之前给op-2插入了op-1全局屏障，致使独立跨臂动作串行。

修复：TaskExpander默认保留legacy串行行为，仅v4显式关闭隐式全局屏障；DAG仍负责同臂链，用户depends_on始终保留，同一物理source（包括不同entity别名）仍按输入顺序依赖。新增完整Pipeline跨臂独立、显式依赖、同臂串行及物理source别名测试。

原始真实Qwen响应在新代码上无网络重放通过，保存 `replayed_commands_after_fix.json`；首次失败和修复前重放均保留。9项v4专项通过。全量运行1828通过、31跳过（该次收集在新增最后一项别名测试前；最后一项随后专项通过）。该契约为测试fixture，不代表实际Control宣告v4能力；无真实场景发布或控制执行。
# v4 对象读写依赖补充（2026-11-27）

取消旧全局屏障后，补充按真实对象ID的actor/reference依赖：先操作某对象后将其作为destination/reference时等待前者；先作为参照后操作该对象时等待已有使用者。不同entity别名不会绕过对象身份。明确hold milestone仍替代对应的完整操作等待，由后续hold技能边处理。

两个不同source共享同一destination不产生完整操作屏障，仍由DAG placement资源窗口处理，避免回退成整段串行。新增正反顺序及共享目的地测试；Python3.11/3.12的v4 pipeline、holds、resources专项各24通过。仅修改v4展开选项，legacy默认串行策略不变。未调用Control或发布场景；最新全量和wheel需在后续最终审计重跑。
# L05 等比例字体浏览器验收（2026-11-27）

在独立新会话明确输入“在桌面上用30个荔枝摆成字母A，间距自动调整”，不是对12苹果请求的自动替换。隔离Brain8503已加载等比映射与最新源码（PID3395047），生产服务未改。

会话749b4c39544f4697abba25a3c8e84eba，任务f5c043609c6b41c8ae3b97ad9b15138a：一次真实U，30个lychee对象、版本1、executed=false。独立核对全部slot与最终Transform：X/Y同一比例0.6687109986436711米，字体revision为font-outline-v1:ae7b7855e115a5966d8b1b3f80f254ccc117ec86f9965e202ee2940453837280。Gateway绑定相机截图与发布digest一致，已查看字母A轮廓。

证据 `var/layout-dual-audit/web-20261127-01/text-a-isotropic-browser-success/` 包含截图、Scene、capture、verification。原12苹果失败记录继续保留；此次成功不宣称任意资产、任意文字或密度均可放置。无控制调用。
# at_least 显式行列数量贯通（2026-11-27）

修复“至少5个、两行三列”只创建5个的不一致。grid/checker显式行列在满足下限时生成全部6槽位；不足下限拒绝，超过1000拒绝。多资产明确数量不匹配时不猜测补哪一种。actual slots/资产展开/ID预留/Scene提交/arrangement记录使用同一结果，assumptions记录requested/resolved及explicit_grid_at_least原因。

新增grid/checker实际实例数、单次版本、resolution成员数、下限冲突、多资产分配冲突、session记录和幂等重放测试。Python3.11/3.12相关90项均通过。该修改仅实现at_least显式维度语义，不声称auto容量缩减已完成；exact行为不变。当前运行服务尚未加载此轮修改。
# at_least 多资产明确数量（2026-11-27）

扩展数量一致性：未指定固定行列时，counts或非循环sequence中明确给出的6个成员满足at_least=5，保留全部成员；总数不足下限、exact不一致和超过1000仍拒绝，不猜测补什么资产。实例结果记录explicit_assets_at_least而非误报explicit_grid_at_least。

规划器测试覆盖counts/sequence、下限、exact回归和容量上限；真实SceneEditor测试确认3苹果3香蕉的count-only grid一次提交。首次测试使用0.15m线型时发生真实香蕉碰撞，测试夹具改为明确0.25m网格以隔离数量行为，没有改碰撞代码或资产尺寸。Python3.11/3.12相关各94通过。自动几何容量搜索仍是独立未完成项。
# 自动数量授权范围契约（2026-11-27）

增加items.min_count/max_count（Compact ql/qu），成对strict整数1–1000且包含requested_count；仅auto且auto_count=true允许。缺一端、越界、反向、布尔/浮点及exact冒用均拒绝。旧无范围输入仍可读取，但不据此虚构允许缩减范围。

新增范围无损Compact往返和8种非法组合测试，重新生成公开/打包Schema。本轮仅建立可校验范围，尚未接入几何数量搜索，不宣称auto容量调整完成。下一步需在该范围内搜索，并确保ID预留、实际成员记录和事务一次提交使用有效数量。
# 已授权数量搜索接入（2026-11-27）

新增layout_quantity.quantity_candidates并接入Pipeline布局事务：create/append的single或显式循环checker/alternating按请求数量距离、同距小数量优先，在min/max内重算slot；原本count不变的首个候选仍先尝试。只重试collision/capacity/workspace，其余错误不重试。实际spec/plan用于实例绑定及arrangement记录，assumptions记录preferred/resolved/attempts。

一次预留授权上限ID范围，候选不发布，成功只提交一次；失败预留仍消耗，不复用。明确per-asset totals、非循环sequence、rearrange/replace不改变成员数量；旧无范围auto不会被默认放宽。新增真实几何缩减成功、范围穷尽、幂等、成员记录、稳定候选顺序、exact和混合数量保护等5项测试通过。尚需append专项及真实Qwen/浏览器范围验收，不把这些未测项标为完成。
