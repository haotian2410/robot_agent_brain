"""Scene editing scale policy, independent of robot movement distances."""
import math
from pydantic import BaseModel, ConfigDict, Field, model_validator


class SceneScalePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    minimum: float = Field(default=.1, gt=0)
    maximum: float = Field(default=10., gt=0)
    small: float = Field(default=1.1, gt=1)
    medium: float = Field(default=1.5, gt=1)
    large: float = Field(default=2., gt=1)

    @model_validator(mode="after")
    def bounds(self):
        if self.minimum > self.maximum or not self.small <= self.medium <= self.large:
            raise ValueError("scene_scale_policy_invalid")
        return self

    def calculate(self, current, edit, asset):
        if asset.scalable is not True:
            raise ValueError("scene_scale_forbidden" if asset.scalable is False else "scene_scale_permission_unknown")
        if asset.scale_range is None:
            raise ValueError("scene_scale_range_unknown")
        if edit.scale_direction:
            factor = getattr(self, edit.scale_amount)
            factor = factor if edit.scale_direction == "enlarge" else 1 / factor
            result = tuple(v * factor for v in current)
        elif edit.scale_mode == "set":
            result = tuple(edit.scale_xyz)
        else:
            result = tuple(v * f for v, f in zip(current, edit.scale_xyz))
        low, high = max(self.minimum, asset.scale_range[0]), min(self.maximum, asset.scale_range[1])
        if not all(math.isfinite(v) and low <= v <= high for v in result):
            raise ValueError(f"scene_scale_out_of_range: allowed [{low}, {high}]")
        return result
