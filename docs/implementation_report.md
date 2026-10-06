# Implementation progress — 2026-10-06

Specification: `robot_agent_brain_codex_implementation_plan.md`, supplied by the user.
Baseline: `266ebcc94fd5b433ebe1000f4d04c7356b747faa`, branch `main`.
Initial working tree was clean; baseline suite had 26 passing tests.

This is an in-progress implementation, **not overall acceptance**.

## Implemented foundation

- `pipeline.py`: explicit `understand_turn` and provider-free `process_turn`;
  compatibility `run`/`run_turn` delegate to them. Original user text is retained.
- `session/brain_session.py`: parsed-turn entry point, with pause checks before
  processing; paused sessions may resume or close.
- `contracts/commands.py`: nested JSON Schema hooks derive per-skill parameter
  rules from `PARAMETER_TYPES`; one canonical wire serialization excludes nulls
  and validates against the public schema.
- `adapters/json_command_sink.py`: validates before writing, stages in the same
  directory, reads back and validates before replacement.
- `pyproject.toml`: adds jsonschema runtime dependency (>=4.23,<5).
- `brain_tests/test_pipeline_stages.py`: provider call counts, original text,
  parsed entry point, query/control bypass, compatibility wrapper.
- `brain_tests/test_export_roundtrip.py`: all seven skills, both MOVE forms,
  final file schema validation, forbidden parameters, failed-write preservation.

## Verification so far

Command:

```bash
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pytest -q brain_tests
```

Result after application integration: **114 passed**. `git diff --check` passed.
Installed independent schema validator: jsonschema 4.26.0.

Real Qwen: **not run**. Wheel outside-source acceptance: **not yet run**.
No frontend/Control integration or robot execution was performed.

## Configuration/assets stage

- Added `config.py` and packaged `resources/config.json`, `defaults.json`,
  `assets.json`: package defaults < configuration file < ROBOT_BRAIN_* environment
  < explicit overrides. API key excluded from serialization.
- Added strict asset index loading and `scene/asset_resolver.py`: duplicate IDs,
  finite dimensions/AABB, aliases, color constraints, copy isolation; concrete
  names never silently substitute another asset of the same category.
- Demo assets are metadata only (center-origin boxes), not actual meshes or
  implemented rendering materials. No task objects are instantiated by loading
  these resources. Real asset file errors do not fall back to demo resources.
- Added `brain_tests/test_config_assets.py` (9 cases). Bootstrap does not yet exist.

## Initial bootstrap stage

- Added pure `SceneBootstrapper.prepare` and `BootstrapResult` with version-scoped
  generated candidate IDs, assumptions and asset bindings. It neither calls a
  provider nor writes/loads a platform or executes the task.
- Generation uses task identities/counts, configured base table and bounded seeded
  layout; placement goals are not used as initial relations. Initial inside/on
  geometry is explicitly unsupported until corresponding metadata support exists.
- Candidate-pool generation still selects through the shared relation resolver;
  generated binding overrides now validate names/colors/exclusions before use.
- Editor lifecycle analysis excludes add targets from the initial scene and
  identifies pre-existing references; pure removal without a scene is blocked.
- Tests prove two-candidate selection, non-fixed objects, deterministic geometry,
  no second understanding, explicit unsupported relation/quantity errors.
- The application/first-add placement-context connection remains pending. This
  stage alone does not yet make the CLI or all B01–B17 cases usable.

## Remaining specification work

Application stage: `BrainApplication.handle` connects one understanding call to
import/generated/session scene routes, parsed processing, report and validated
artifact publication. Tests inject a deterministic Provider (not real Qwen) and
verify matching snapshot/commands, repeated export, no-scene query versus uploaded
empty scene, missing objects not generated, and committed scene retained on disk
failure. CLI, persistence, richer error mapping/debug redaction, configuration
fingerprints and final failure matrix are still pending.

First-add integration: explicit `edit_defaults` is passed through Session/Pipeline;
the editor does not infer initialization from version zero. Add uses asset color
declarations and preserves aliases. New instance bindings are held within the
ordered preview for add-then-move, before dialogue bindings are considered.
Tests cover multiple add counts, same-turn stable identity and refusal to invent
a placement when no default context is supplied. Application wiring, richer
layout constraints and legacy bootstrap-reference adaptation remain pending.

Artifact foundation: added BrainIssue/BrainError, BrainRunReport, strict flat scene
codec, and LocalScenePlatform (capture explicitly unsupported). ArtifactWriter
validates and reads back schemas in a private staging directory, then publishes a
new request directory. Old paths are not copied into failed reports; input files
are read-only; traversal and overwrite tests pass. Application orchestration and
platform-ack-versus-disk-failure reporting are still pending, so this does not yet
claim end-to-end publication acceptance.

Session migration: exporting commands now updates `last_exported_request` (and
legacy `last_request_id`) but does NOT set pending. External integration must call
`mark_dispatched(commands)` with an unchanged, version-matched plan exported by
this session. Confirmed holding changes only on validated feedback. Feedback
without a newer confirmed snapshot marks geometry unknown, including partial or
failed execution. Source is explicitly `external` or `simulated`. Empty sessions
support pause/resume/close without constructing a scene. Persistence and full
feedback/refresh adapter documentation are still pending.

Query/focus stage: `SceneQueryIntent` accepts shared entities/selection relations;
legacy fields remain supported, mixed selector formats fail explicitly. Query
aggregation permits zero/multiple matches and returns matched IDs for every kind.
Pipeline exposes focus/deleted IDs and dialogue observes successful edit/query
results as well as robot tasks. Added `test_query_focus.py` for color, empty/no
scene distinction, edit/query/delete focus and singular/plural ambiguity.
Same-turn add identity and query Prompt examples remain to be integrated.

Latest foundation fixes: SceneManager revalidates incoming patches and complete
candidate scenes before committing. Retired IDs cannot be revived within or
across patches. Action payloads are exclusive. Compound GRASP/MOVE/RELEASE uses
one temporary holding state; independent MOVE still grasps/releases. Unsupported
SEARCH and invalid release/double grasp explicitly fail. PlanValidator and full
execution profile integration are still pending.

Old-test migration: `test_task_expansion_produces_concrete_commands_for_all_members`
previously expected consecutive double grasp to export. It now retains both
expanded objects, asserts single-gripper refusal, and checks concrete wire targets
using LOCATE. This implements P03 without silently changing the user task.

- Finish T01 normalization/missing-distance evidence and T07 non-finite/schema
  edge cases; complete application-level readback validation with ArtifactWriter.
- Finish T02 configuration/layout bounds validation and integrate resources into bootstrap/application.
- T03 bootstrap lifecycle, constrained initial layout and validated candidates.
- T04 atomic editor context, same-turn identities, scene/payload invariants.
- T05 holding-aware compound recipes and semantic PlanValidator.
- T06 shared query selectors and cross-branch dialogue focus.
- T08 application reports/errors, codecs, local platform, artifact publication.
- T09 exported versus dispatched state, feedback and session persistence.
- T10 run/chat/batch/schemas, replay labeling and provider diagnostics.
- T11 B01–C03 acceptance matrix and optional real Qwen tests.
- T12 README/manual/contracts, clean wheel CLI acceptance and CI expansion.

The initial `robot-brain run/chat/schemas` CLI exists; batch and persisted recovery
are still pending. Brain-native scene/commands formats
remain distinct from the team's unfinalized components/taskStep interfaces.

## Initial CLI verification

Latest suite: **118 passed**. Four new subprocess tests validate scene-optional
replay run, clean JSON stdout, exact-input replay refusal and schemas without a
model. These source-tree tests do NOT constitute wheel outside-source acceptance.
`--session` currently selects only an in-process session, not disk recovery.
Real Qwen has not been run; replay fixtures are explicitly labeled.

## Batch verification

Latest suite: **119 passed**. JSONL batches reuse a session within each group,
skip dependent cases after failures, continue independent groups, and publish a
provider-labeled summary with expected report/artifact checks. This is replay/
injected-provider validation, not real model acceptance.

## Session recovery verification

Latest suite: **126 passed**. `session/store.py` adds validated, versioned JSON
checkpoints, atomic replacement and non-blocking POSIX per-session locks. The
Application restores scene/IDs/focus/pause/sync/exported and dispatched state;
independent app instances refresh newer revisions. Corrupt checkpoints and
symlink/traversal targets fail instead of silently starting fresh. This local
Linux/POSIX implementation does not claim distributed/network-filesystem locking.
Application dispatch additionally requires the matching published command file.
Validated feedback is checkpointed; missing confirmed geometry remains unknown
after restart. `--session` now resumes under the same output directory.
Publication failure preserves confirmed in-memory state and attempts a checkpoint
before publishing artifacts; a failed disk write cannot guarantee recovery.

## HTTP diagnostics verification

Latest suite: **138 passed**. Existing Qwen adapter now accepts an injected
httpx client/transport. Each call records one outcome including conversion and
Pydantic failures, duration, request IDs, model/endpoint summary, available usage
and finish reason. Truncated/malformed output is retained in memory for debug
before parsing; normal metrics do not contain raw response bodies. API-key text
is redacted from diagnostic messages. Twelve tests cover success, malformed JSON,
empty/non-text choices, truncation, validation, HTTP errors, timeout and per-turn
log slicing. They use MockTransport, **not a real Qwen service**.

## Independent plan gate

Latest suite: **147 passed**. `PlanValidator` now guards `CommandExporter` itself,
including direct callers: concrete existing targets, scene version, operation
coverage/order/dependencies, effect counts, grasp/move/release preconditions and
placement roles. Confirmed holding is an explicit optional exporter input; plans
do not update it. Tests mutate otherwise valid plans to remove steps, alter roles,
add motion or reference missing objects. Three existing export fixtures now
include their actual target objects instead of an empty scene; all original
wire-format assertions are retained. This is semantic validation, not collision,
IK or actual execution verification. Quantity expansion still needs final audit.

## Collection pairing regression

Latest suite: **150 passed**. A single pairwise operation with two collection
roles now expands every corresponding pair instead of retaining only the first.
Separate scalar-destination operations still allocate distinct source members
in language order. Incomplete distributed pairing and unequal cardinalities are
blocked without dropping objects. Existing red-box/blue-box pairing tests remain
unchanged and pass. Full specification acceptance, packaging and final docs
remain pending; these local commits have not been pushed.

## Motion evidence, collection editing and local pronouns

Latest suite: **164 passed**. Missing linguistic distance/scale is now blocked
even when the provider supplied a plausible number; both native scene edits and
robot moves share this gate. Explicit distances and small/medium/large evidence
remain supported, with basic English directional phrases added. HTTP conversion
preserves motion-evidence error codes so missing user facts are not labeled a
network failure. The old vague-motion test now asserts refusal (its former .01m
expectation contradicted P05). The atomic two-move test supplies its intended
5cm/10cm distances explicitly and retains all transform-preservation assertions.

SceneEditor validates affected objects against the complete prospective scene:
new-new collisions are caught, and old positions of simultaneously moved objects
do not cause false collisions. Late failures leave the input scene unchanged.

Pipeline defers missing/ambiguous prior-focus errors until the one understanding
call can identify a valid ordered add-then-reference lifecycle. Same-turn local
IDs can therefore resolve without a prior focus; unresolved cross-turn pronouns
still fail. This does not add a second understanding call.

## First outside-checkout wheel acceptance — 2026-10-07

Core revision tested: `039114a`. Built with Python 3.12 using `pip wheel`, installed
into a fresh venv without system site packages, then ran from `/tmp` with
`PYTHONPATH` removed. Wheel SHA256:
`6cd0afc55e61fe9428fbdd0d588d30accd4f944583e47c5eff2b86e9df0d6efa`.

```bash
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m pip wheel --wheel-dir /tmp/brain-wheel-audit-dWyV3yio/wheels .
/home/cscvlab/miniconda3/envs/robot_agent_integ/bin/python -m venv /tmp/brain-wheel-audit-dWyV3yio/env
/tmp/brain-wheel-audit-dWyV3yio/env/bin/python -m pip install --no-index --find-links /tmp/brain-wheel-audit-dWyV3yio/wheels robot-agent-brain
cd /tmp
env -u PYTHONPATH /tmp/brain-wheel-audit-dWyV3yio/env/bin/python /home/cscvlab/lht/robot_agent_brain/scripts/wheel_smoke.py
```

Result: **passed**. Imported module came from the new venv's site-packages, not
the checkout. Console help, prompt/default/asset resources, schema export,
replay robot task with no scene, two generated apples, matching scene/commands,
independent schema validation, and second-process recovery all passed. Evidence
directory: `/tmp/brain-wheel-smoke-sqzgj_9q` (temporary local test output, not
committed). `scripts/wheel_smoke.py` is also wired into both existing CI Python
3.11/3.12 jobs. Only 3.12 was exercised locally; no remote CI result claimed.

Real Qwen availability check: `curl --noproxy '*' --max-time 3 --silent
--show-error http://127.0.0.1:8080/v1/models` failed with connection refused
(exit 7). **Real Qwen task acceptance was not run**. No service was started or
replay substituted for it. Final acceptance still requires remaining behavioral
audit and current documentation, and rebuilding the final revision's wheel.

## Documentation and diagnostics stage — 2026-10-07

Latest full suite: **171 passed**. Added README CLI/config/artifact instructions,
`docs/manual_testing.md`, `docs/contracts.md`, explicit replay fixtures and a
three-case JSONL batch. The documented batch was actually run (3 passed, 0 failed,
0 skipped) under `/tmp/brain-manual-doc-audit`; it is not a real-Qwen result.

Request records/checkpoints now include a nonsecret configuration fingerprint
(provider/model/endpoint summary, robot/seed, prompt/asset/default hashes).
Recovery with changed configuration warns without recreating confirmed objects.
`--debug` publishes per-turn semantic and plan artifacts plus redacted raw
response/call/failure records; normal runs omit raw diagnostics. New tests verify
secret omission and failure logs. Prompt examples now use shared edit/query
selectors, explicit all_available, same-turn precedence and missing-distance
clarification; all JSON examples are parser-validated.

Legacy name-only bootstrap references can be completed by unique asset names or
aliases. First-add all_available no longer silently creates one object: configured
initial counts are required. A paused empty session is checked before bootstrap,
so refusal does not create a scene as a side effect. Batch no longer exposes
ignored scene/session CLI options.

The older sections above are chronological stage records, not a current list of
missing features. Final audit/document consolidation and final-revision wheel
rebuild remain required. Remaining risks to audit include bounded relative-add
layout, full schema edge cases, restore metadata compatibility, failure-state
reporting and acceptance coverage against every numbered specification item.

## Layout and restore edge audit

Latest suite: **181 passed**. Relative add now uses a bounded perpendicular
search, preserving the requested directional relation and configured initial
workspace bounds. Failed placement does not shrink counts or mutate the source
scene. Supporting surface contact is not treated as clearance penetration.
`SceneConfig.schema_version` is now a Literal 1.0; recursive finite-JSON checks
reject NaN/Infinity in nested scene properties before platform commit.

Numeric wire tests independently reject non-JSON NaN/Infinity at decoding, then
use the public JSON Schema for JSON-domain values. Python's permissive default
JSON decoder is not evidence that those tokens are valid JSON; no claim is made
that a standard schema alone defines behavior on Python NaN objects.

Added `SceneEditResult` with patch, focus, created/deleted IDs and local bindings;
the legacy `edit()` method still returns its patch. Pipeline consumes the explicit
editor outcome. Restored asset IDs are checked against the configured catalog;
Application lock/restore failures return a complete non-delivery report with
zero model calls instead of escaping before report construction. Regression
tests cover corrupt checkpoints and concurrent writer refusal.

## Requirement-indexed acceptance expansion

Latest suite: **200 passed**. Added `docs/acceptance_matrix.md`, mapping every
B01–C03 behavioral item and T01–T12 work item to concrete evidence and identifying
remaining final gates. New tests check initial non-overlap rather than relying
only on absence of containment properties, first-turn movement exactly once,
invalid upload refusal before model calls, bounded workspace failure, world/local
rotation numerical results, query snapshot preservation, and success-then-failure
artifact isolation.

Grounding now validates candidate-pool cardinality before relation filtering, so
an override cannot shrink two candidates to the wrong single object and then
claim it is rightmost. Collection editing followed by plural editing preserves
both IDs. Feedback duplicate/foreign IDs, incomplete success, unknown holding and
old confirmed snapshots are tested as no-state-change failures. Local CLI vision
configuration is rejected without a rendering/detection adapter, rather than
ignored or supplied mock image data. Real Qwen remains untested/unavailable.

## Configuration/geometry audit

Latest full suite: **205 passed**. Added regression evidence that first-add layout
uses the configured seed and clearance, is repeatable for the same inputs, and
changes with a different seed. Bootstrap refuses a workspace extending beyond
the configured table's dimensions/AABB. Asset resolution and grounded overrides
now enforce category constraints even for exact names; configured category aliases
are passed consistently through robot, shared edit selector and query selection.
Legacy name-only reference inference remains explicitly separate from user
category constraints. Final wheel rebuild follows this code revision.
