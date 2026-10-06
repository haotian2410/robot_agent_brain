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

Result after dispatch/feedback stage: **97 passed**. `git diff --check` passed.
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

There is not yet a usable `robot-brain` CLI. Brain-native scene/commands formats
remain distinct from the team's unfinalized components/taskStep interfaces.
