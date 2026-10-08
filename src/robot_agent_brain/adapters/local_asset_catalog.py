from ..contracts.model_property import ModelProperty
from ..contracts.asset_library import LibraryAssetId
import json
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class AssetDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    models: list[ModelProperty]
    demo_assets: bool = False
    library_ids: dict[str, LibraryAssetId] = Field(default_factory=dict)
    aliases: dict[str, str] = Field(default_factory=dict)
    category_aliases: dict[str, str] = Field(default_factory=dict)
    overridable_properties: dict[str, list[str]] = Field(default_factory=dict)
    intrinsic_properties: dict[str, dict[str, str | float | bool]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_index(self):
        ids = [m.asset_id for m in self.models]
        if len(ids) != len(set(ids)):
            raise ValueError("asset_id_duplicate")
        if len(set(self.library_ids.values())) != len(self.library_ids):
            raise ValueError("library_asset_id_duplicate")
        for aliases, canonical in ((self.aliases, {m.semantic_name.casefold() for m in self.models}),
                                   (self.category_aliases, {m.category.casefold() for m in self.models})):
            normalized = {}
            for alias, name in aliases.items():
                key, value = alias.strip().casefold(), name.strip().casefold()
                if not key or value not in canonical or (key in canonical and key != value):
                    raise ValueError("asset_alias_invalid")
                if key in normalized and normalized[key] != value:
                    raise ValueError("asset_alias_conflict")
                normalized[key] = value
        if not (set(self.overridable_properties) | set(self.intrinsic_properties)) <= set(ids):
            raise ValueError("asset_metadata_unknown_id")
        return self


class LocalAssetCatalog:
    def __init__(self, models: list[ModelProperty] | None = None):
        self._models = {}
        self.metadata = AssetDocument(models=models or [])
        for item in self.metadata.models:
            self.add(item)

    @classmethod
    def from_document(cls, value):
        document = AssetDocument.model_validate(value)
        catalog = cls(document.models)
        catalog.metadata = document
        return catalog

    @classmethod
    def from_file(cls, path):
        return cls.from_document(json.loads(Path(path).read_text(encoding="utf-8")))

    def add(self, model: ModelProperty) -> None:
        model = ModelProperty.model_validate(model.model_dump())
        if model.asset_id in self._models:
            raise ValueError("asset_id_duplicate: " + model.asset_id)
        self._models[model.asset_id] = model.model_copy(deep=True)
        if model.asset_id not in {item.asset_id for item in self.metadata.models}:
            self.metadata.models.append(model.model_copy(deep=True))

    def find_models(self, semantic_name: str, category: str) -> list[ModelProperty]:
        return [m.model_copy(deep=True) for m in self._models.values()
                if m.semantic_name.casefold() == semantic_name.casefold()
                and m.category.casefold() == category.casefold()]

    def get_model_property(self, asset_id: str) -> ModelProperty:
        try:
            return self._models[asset_id].model_copy(deep=True)
        except KeyError as exc:
            raise LookupError(f"asset_model_property_missing: {asset_id}") from exc
