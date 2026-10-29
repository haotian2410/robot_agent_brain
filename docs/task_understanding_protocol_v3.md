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
