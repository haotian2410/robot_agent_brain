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
