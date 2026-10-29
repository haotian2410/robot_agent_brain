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
compatibility. Live scene-edit responses additionally record
`protocol_version=task_understanding.v3`, parser stage, canonical references,
and the original model response in debug diagnostics. No coordinates, IK or
execution details are added to the semantic response.
