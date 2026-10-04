from pydantic import BaseModel, ConfigDict, Field
from ..contracts.task_intent import MotionScale


class MotionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    small_scale_factor: float = Field(default=0.10, gt=0)
    medium_scale_factor: float = Field(default=0.50, gt=0)
    large_scale_factor: float = Field(default=2.00, gt=0)

    def scale_factor(self, scale: MotionScale) -> float:
        return {
            MotionScale.SMALL: self.small_scale_factor,
            MotionScale.MEDIUM: self.medium_scale_factor,
            MotionScale.LARGE: self.large_scale_factor,
        }[scale]

