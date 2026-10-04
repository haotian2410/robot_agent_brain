from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.camera import CameraFrame


class VisionEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: str
    semantic_name: str


class VisionGroundingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)
    frame: CameraFrame
    entities: list[VisionEntity]


class Detection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity: str
    bbox: tuple[int, int, int, int]

    @model_validator(mode="after")
    def valid_box(self):
        y1, x1, y2, x2 = self.bbox
        if not (0 <= y1 < y2 <= 1000 and 0 <= x1 < x2 <= 1000):
            raise ValueError("invalid normalized bbox")
        return self


class VisionGroundingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detections: list[Detection] = Field(default_factory=list)
