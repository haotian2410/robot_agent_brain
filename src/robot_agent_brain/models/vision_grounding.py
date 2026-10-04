from pydantic import BaseModel, ConfigDict, Field
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


class VisionGroundingOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detections: list[Detection] = Field(default_factory=list)

