"""Bind logical environment references to current/original scene objects."""
from dataclasses import dataclass

from ..errors import BrainError
from ..semantics.scene_references import CanonicalReference, RefScope, SceneReferenceCatalog
from ..scene.component_access import SceneIndex


@dataclass(frozen=True)
class ResolvedSceneReference:
    raw_value: str
    canonical_id: str
    scope: str  # entity | scene_ref | anchor
    kind: str
    object_id: int | None = None
    source: str = ""

    def canonical(self):
        return CanonicalReference(raw_value=self.raw_value, canonical_value=self.canonical_id,
                                  scope=RefScope(self.scope), kind=self.kind,
                                  resolved_object_id=self.object_id)


class SceneReferenceResolver:
    def __init__(self, catalog=None, *, table_metadata_ref=None):
        self.catalog = catalog or SceneReferenceCatalog()
        self.table_metadata_ref = table_metadata_ref

    @staticmethod
    def _entity_ids(entities):
        return {getattr(entity, "entity_id", None) for entity in (entities or [])}

    @staticmethod
    def _key(value):
        return str(value).strip().casefold().replace("-", "_")

    def _scene_candidates(self, selector, spec, scene):
        if scene is None:
            return []
        index = SceneIndex(scene)
        raw = self._key(selector)
        candidates = []
        for obj in scene.objects:
            identifier = obj.object_id_in_scene
            if index.metadata_type(identifier) == "robot":
                continue
            semantic = index.semantic(identifier)
            object_name = self._key(obj.object_name_in_scene or "")
            if str(identifier) == str(selector) or object_name == raw:
                candidates.append(identifier)
                continue
            if spec is not None and spec.canonical_id == "table" and self.table_metadata_ref is not None:
                if index.metadata_ref(identifier) == self.table_metadata_ref:
                    candidates.append(identifier)
                    continue
            if semantic is None:
                continue
            name = str(semantic.semantic_name or "").strip().casefold().replace("-", "_")
            if spec is not None and (name == spec.canonical_id or (spec.canonical_id == "table" and
                    semantic.category == "surface" and name in {"table", "work_table", "工作台", "桌子"})):
                candidates.append(identifier)
            elif spec is None and name == raw:
                candidates.append(identifier)
        return candidates

    def resolve(self, selector, *, entities=None, scene=None, default_surface_id=None,
                scene_basis="current"):
        if not isinstance(selector, str) or not selector.strip():
            raise BrainError("scene_reference_unresolved", "reference_resolution",
                             "scene reference is empty", category="semantic_protocol", value=selector)
        raw = selector.strip()
        if raw in self._entity_ids(entities):
            return ResolvedSceneReference(raw, raw, "entity", "task_entity", source="declared_entity")
        spec = self.catalog.lookup(raw)
        candidates = self._scene_candidates(raw, spec, scene)
        if len(candidates) > 1:
            raise BrainError("scene_reference_ambiguous", "reference_resolution",
                             f"multiple scene objects match {(spec.canonical_id if spec else raw)!r}",
                             category="semantic_protocol", value=raw,
                             candidates=candidates)
        if len(candidates) == 1:
            canonical_id = spec.canonical_id if spec is not None else self._key(raw)
            kind = spec.kind if spec is not None else "scene_object"
            return ResolvedSceneReference(raw, canonical_id, "scene_ref", kind,
                                          candidates[0], source=f"{scene_basis}_scene")
        if spec is None:
            raise BrainError("scene_reference_unresolved", "reference_resolution",
                             f"no registered scene reference or scene object matches {raw!r}",
                             category="semantic_protocol", value=raw)
        if spec.allow_default and default_surface_id is not None:
            if scene is None:
                return ResolvedSceneReference(raw, spec.canonical_id, "anchor", spec.kind,
                                              default_surface_id, source="environment_catalog")
            ids = {obj.object_id_in_scene for obj in scene.objects}
            if default_surface_id in ids:
                return ResolvedSceneReference(raw, spec.canonical_id, "anchor", spec.kind,
                                              default_surface_id, source="configured_default_surface")
        raise BrainError("scene_reference_unresolved", "reference_resolution",
                         f"scene reference {raw!r} is not bound in the {scene_basis} scene",
                         category="semantic_protocol", value=raw)

    def resolve_all(self, selectors, **kwargs):
        return [self.resolve(selector, **kwargs) for selector in selectors]
