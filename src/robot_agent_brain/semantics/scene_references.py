"""Configurable logical references to environment objects.

These are not assets and are never passed to ``AssetResolver``.  They are
semantic names that must be bound to a concrete scene object before geometry
or editing code can use them.
"""
from dataclasses import dataclass
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


class RefScope(StrEnum):
    ENTITY = "entity"
    SCENE_REF = "scene_ref"
    ANCHOR = "anchor"


class CanonicalReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_value: str = Field(min_length=1)
    canonical_value: str = Field(min_length=1)
    scope: RefScope
    kind: str | None = None
    resolved_object_id: int | None = None


@dataclass(frozen=True)
class SceneReferenceSpec:
    canonical_id: str
    aliases: tuple[str, ...]
    kind: str
    selector: str = "semantic"
    allow_default: bool = False


class SceneReferenceCatalog:
    def __init__(self, specs=None):
        self._specs: dict[str, SceneReferenceSpec] = {}
        self._aliases: dict[str, str] = {}
        for spec in specs or self._defaults():
            self.register(spec)

    @staticmethod
    def _defaults():
        return [SceneReferenceSpec(
            canonical_id="table",
            aliases=("table", "desk", "desktop", "桌子", "桌面", "台面"),
            kind="support_surface", allow_default=True,
        )]

    @staticmethod
    def _key(value):
        return str(value).strip().casefold().replace("-", "_")

    def register(self, spec: SceneReferenceSpec):
        canonical = self._key(spec.canonical_id)
        if canonical in self._specs and self._specs[canonical] != spec:
            raise ValueError("scene_reference_catalog_conflict: " + canonical)
        normalized = SceneReferenceSpec(canonical, tuple(spec.aliases), spec.kind,
                                        spec.selector, spec.allow_default)
        self._specs[canonical] = normalized
        for alias in (canonical, *spec.aliases):
            key = self._key(alias)
            previous = self._aliases.get(key)
            if previous is not None and previous != canonical:
                raise ValueError("scene_reference_alias_conflict: " + key)
            self._aliases[key] = canonical

    def lookup(self, selector):
        if selector is None:
            return None
        canonical = self._aliases.get(self._key(selector))
        return self._specs.get(canonical) if canonical else None

    def canonical(self, selector):
        spec = self.lookup(selector)
        return spec.canonical_id if spec else None

    def aliases(self):
        return dict(self._aliases)

    def specs(self):
        return tuple(self._specs.values())
