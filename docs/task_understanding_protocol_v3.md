# Task understanding protocol v3

The live Qwen adapter now follows a staged path:

```text
Qwen v2/v3 JSON -> wire envelope -> canonical entity/reference model
                 -> scene reference resolver -> semantic/capability checks
                 -> SceneBootstrapper/SceneEditor
```

`id`/`name` are accepted as v2 aliases and normalized to `entity_id`/`semantic_name`.
Scene references such as `table`, `desk`, `桌面` are not task entities and are
bound only through the configured `SceneReferenceCatalog`. Unknown references
are reported as `scene_reference_unresolved`; multiple matching scene objects
are reported as `scene_reference_ambiguous`.

The Brain keeps the original v2 prompt and replay/direct model validation for
compatibility. Legacy `TaskParseOutput` responses are marked
`protocol_version=task_understanding.v2` and adapted to the same canonical
turn shape; the staged scene-edit wire path defaults to v3. Live responses
record the parser stage, canonical references, and the original model response
in debug diagnostics. `models.protocol_migration.compare_v2_v3` provides an
offline shadow comparison that ignores only the envelope version and compares
canonical semantic payloads. No coordinates, IK or execution details are added
to the semantic response.

## Spatial semantics

Spatial language is shared by `scene_edit`, `robot_task` and `scene_query`; the
route depends only on who performs the action and whether a new object is
created, never on a direction or region word.

`relations[]` uses one shape on all three routes:
`{"scope","subject","relation","reference"}`. Half relations (`left`, `right`,
`front`, `back`, `up`, `down`) take an optional reference — null splits the
candidate pool around the world origin, a support surface such as `table`
splits it around that surface and excludes the surface itself. Extrema
(`leftmost` … `lowest`) ignore `reference`, so it must stay null. Binary
relations must carry one. `scene_query.predicate` is restricted to the seven
directional predicates `SceneQueryIntent` declares and only pairs with
`query_type=relation`; `near`/`nearest` select the closest candidate instead of
verifying proximity, so "is there an apple beside the basket" stays a
`neighbors` query. The accepted values, the tabletop region vocabulary and the
interaction verbs are generated into the prompt from the live contracts by
`models.prompts.build_spatial_reference_tables`, so a prompt cannot document a
token Python rejects.

Placement differs by route. The editor resolves `placement_region`/
`placement_hint` into concrete grid candidates through `SceneLayoutPolicy`.
A robot placement keeps the same eight tokens in
`PlacementTarget.region`, which `CommandPlacementTarget` exports unchanged: it
records the requested tabletop region and does not compute or guarantee a
collision-free landing point. `semantics.spatial_phrases` is the single
Chinese-phrase table behind both paths, so an omitted region is filled from the
instruction only when the phrase is anchored on the support surface.

## Default compact U transport (`u.compact.v1`)

`BrainConfig.understanding_wire_format` defaults to `compact_v1` as authorized
on 2026-11-19. Explicit `full` preserves the old complete-field output protocol.
This changes only the Qwen task-understanding boundary, not BrainTurn, Scene,
Gateway, Control, or the D/S/R formats. Existing explicit `full` configurations
are respected; omitted settings use compact after restarting the process.

### Configuration and rollback

The tested compact implementation is promoted from `test/u-compact-strict-20261119` to `main`.
Keep the existing machine-specific configuration, credentials and asset paths.
In a separate copy of the Brain JSON configuration, set the top-level field:

```json
{"understanding_wire_format": "compact_v1"}
```

This is a configuration fragment, not a complete deployment configuration.
Start the test Brain with that configuration; an already-running process does
not change modes when source files or configuration files change. Prefer an
isolated Gateway/session store and set `execution_enabled=false` for plan-only
validation. Frontend and Control do not need the short-field protocol.
To revert the transport, set `understanding_wire_format` to `full` and restart
the test Brain after all tasks finish. No automatic fallback is performed.

The 2026-11-19 compact-only performance sample passed 30/30 semantic audits
without retries (six retained samples and 24 new calls); median output was 209
tokens and median U latency was 6.94 seconds. Historical baseline and dedup
numbers are reference only: cache conditions differ from this compact-only run.
The browser regression still contains three sorting-scene geometry refusals;
these are not advertised as positive edit passes. The corresponding isolated
unobstructed add/move/rotate follow-up passed six turns. Local evidence under
`var/perf/` is intentionally not shipped in Git.

Validation note (2026-11-19): compact_v1 is the default; full remains selectable.
The original empty-bootstrap regression (`add` carrying `ax/ad`) is now guarded
by closed operation-specific schemas generated from `contracts/scene_edit_rules.py`.
That module is shared with the canonical validator; full-mode legacy acceptance
and normalization remain unchanged. In Compact, inapplicable fields are forbidden
even if null/default-valued. Decoder validation runs before legacy normalization;
it never strips invalid fields or selects an arbitrary union branch.

Operation discriminators (`op`, then `t`) MUST precede required branch parameters
in generated property order: the current llama.cpp grammar orders object keys.
Putting required rotation arguments before `op` prevented op-first generation
from choosing rotate in the initial browser pilot. JSON Schema validation alone
cannot reveal this backend behavior. Preserve raw pilot failures and repeat
both empty-bootstrap and post-add rotation against the real model.

The final isolated C5 run passed five empty sessions with add followed by rotate
(10/10 real-browser turns, one U call each, no Control); evidence is in
`var/perf/u-strict-20261119/web/c5-final/audit-wire.json`. The default promotion
does not erase the geometry refusals and cache-comparison limitations recorded
above. Historical compact responses containing invalid fields
are not silently grandfathered into current live parsing.

Both modes send the OLS catalog once, in the stable System prefix. User data
carries `catalog_revision`, instruction, workspace and scene context. The
immutable Python catalog snapshot remains authoritative for asset checks.
The System projection retains names, aliases, tags, availability, placement,
scaling limits, robot boundaries, scene templates and registered profiles;
local metadata paths are not model input. Sorting and hashes are deterministic.

`models/understanding_wire.py` owns the frozen short-field registry, schema,
prompt rendering and schema-directed encoder/decoder. Semantic values are not
abbreviated. Required top-level fields are `v`, `s`, `k`; accepted robot tasks
require nonempty `e` and `o`, edit/query/session routes require `se`/`sq`/`ss`.
Clarification and rejection require `q` and cannot carry executable payloads.
Optional nulls, empty arrays and declared defaults may be omitted. Missing
targets, references and asset choices are never inferred by the codec.

Only schema-defined object keys are translated. Dictionary data and strings
are opaque: an entity color selector is `cl`, but a color edit is
`p={"color":"blue"}`, never `p={"cl":"blue"}`. Relations and references in
edit operations must be paired before the existing canonical parser runs.
Unknown short keys, wrong versions, incomplete routes and wrong payloads fail
closed; there is no silent retry using the other wire dialect. The existing
single missing-asset-choice repair attempt uses the selected dialect.

Debug evidence retains raw wire output and expanded canonical data. Model
call records include wire format, catalog revision, prompt/schema hashes and
all retries. Server `timings` and completion ID are recorded only when returned
on that exact HTTP response; absent timing is not estimated from another call.

Run `brain_tests/test_understanding_compact.py` and
`brain_tests/test_compact_operation_schema.py` for codec/provider regression.
`scripts/check_edit_rule_compatibility.py <report.json>` differentially checks
the full validator against the tracked pre-extraction version, including errors
and its public JSON schema. `scripts/verify_compact_bootstrap_web.py` creates
five truly empty sessions; `scripts/audit_compact_web_wire.py` additionally
checks saved raw responses, schema identity, retry counts and commit receipts.
`scripts/benchmark_understanding_wire.py` performs U-only interleaved comparisons
with a frozen pre-change prompts module, fixed scene and catalog; it never
creates a platform, lease or Control request. It writes full request, raw
response, canonical result, timings and semantic-oracle results for each call.
Interpret first-provider-call separately from actual server cache hits.
`scripts/wheel_understanding_smoke.py` must run outside the checkout against an
installed wheel. Browser integration uses a separate state directory and
`execution_enabled=false`; a successful U parse alone is not an end-to-end pass.
