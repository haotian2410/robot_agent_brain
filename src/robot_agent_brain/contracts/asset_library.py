"""Derived, internal asset geometry. Never serialized into shared Scene wire."""
import math
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


LibraryAssetId = Annotated[int, Field(strict=True, ge=0, le=2**53 - 1)]


class AssetGeometry(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, frozen=True)
    dimensions_m: tuple[float, float, float]
    local_aabb_min_m: tuple[float, float, float] | None
    local_aabb_max_m: tuple[float, float, float] | None

    @model_validator(mode="after")
    def consistent_bounds(self):
        if any(size <= 0 for size in self.dimensions_m):
            raise ValueError("asset_geometry_invalid")
        if self.local_aabb_min_m is None and self.local_aabb_max_m is None:
            return self
        if self.local_aabb_min_m is None or self.local_aabb_max_m is None:
            raise ValueError("asset_geometry_invalid")
        for size, low, high in zip(self.dimensions_m, self.local_aabb_min_m, self.local_aabb_max_m):
            if low >= high or not math.isclose(size, high - low, rel_tol=1e-8, abs_tol=1e-10):
                raise ValueError("asset_geometry_invalid: dimensions must equal positive max-min")
        return self


class BrainAssetView(AssetGeometry):
    library_asset_id: LibraryAssetId
    metadata_ref: str = Field(min_length=1)
    semantic_name: str = Field(min_length=1)
    metadata_path: str | None = None
    category: str | None = None
    asset_type: str = "model"
    tags: tuple[str, ...] = ()
    physical_properties: dict = Field(default_factory=dict)
    grasp_properties: dict = Field(default_factory=dict)
