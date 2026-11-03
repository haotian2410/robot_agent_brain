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


def geometry_from_ols_aabb(value) -> AssetGeometry:
    """Convert OLS's six signed face coordinates to Brain geometry.

    OLS publishes ``[x+, x-, y+, y-, z+, z-]``.  The values are coordinates
    in the asset-local frame, not guaranteed to be ordered or opposite in
    sign (for example a model origin can be outside its mesh).  Treat each
    pair as unordered endpoints and retain the resulting exact local bounds.
    """
    if not isinstance(value, (list, tuple)) or len(value) != 6:
        raise ValueError("asset_aabb6_invalid")
    try:
        values = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("asset_aabb6_invalid") from exc
    if not all(math.isfinite(item) for item in values):
        raise ValueError("asset_aabb6_invalid")
    low = tuple(min(values[index], values[index + 1]) for index in (0, 2, 4))
    high = tuple(max(values[index], values[index + 1]) for index in (0, 2, 4))
    return AssetGeometry(
        dimensions_m=tuple(upper - lower for lower, upper in zip(low, high)),
        local_aabb_min_m=low,
        local_aabb_max_m=high,
    )


class BrainAssetView(AssetGeometry):
    library_asset_id: LibraryAssetId
    metadata_ref: str = Field(min_length=1)
    semantic_name: str = Field(min_length=1)
    metadata_path: str | None = None
    category: str | None = None
    asset_type: str = "model"
    tags: tuple[str, ...] = ()
    color_tags: tuple[str, ...] = ()
    scalable: bool | None = None
    scale_range: tuple[float, float] | None = None
    physical_properties: dict = Field(default_factory=dict)
    grasp_properties: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_scale_range(self):
        if self.scale_range is not None:
            low, high = self.scale_range
            if not (0 < low <= high) or not all(math.isfinite(v) for v in self.scale_range):
                raise ValueError("asset_scale_range_invalid")
        return self
