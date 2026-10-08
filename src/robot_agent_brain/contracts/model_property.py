import math
from pydantic import BaseModel, ConfigDict, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class ModelProperty(StrictModel):
    asset_id: str
    semantic_name: str
    category: str
    dimensions_m: tuple[float, float, float]
    aabb_m: tuple[float, float, float, float, float, float] | None = None

    @model_validator(mode="after")
    def positive_dimensions(self):
        if any(not math.isfinite(value) or value <= 0 for value in self.dimensions_m):
            raise ValueError("dimensions_m must be positive")
        if any(not value.strip() for value in (self.asset_id, self.semantic_name, self.category)):
            raise ValueError("asset identifiers and names must not be empty")
        if self.aabb_m is not None:
            if not all(math.isfinite(v) for v in self.aabb_m) or any(self.aabb_m[i] >= self.aabb_m[i+3] for i in range(3)):
                raise ValueError("invalid asset AABB: expected min xyz then max xyz")
        return self
