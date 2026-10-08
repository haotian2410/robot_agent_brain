from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from .scene import SceneId
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CameraOutput(StrEnum):
    RGB = "rgb"
    DEPTH = "depth"
    SEGMENTATION = "segmentation"


class CameraRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str = "scene_camera"
    width: int = Field(default=640, gt=0)
    height: int = Field(default=480, gt=0)
    outputs: list[CameraOutput] = Field(default_factory=lambda: [CameraOutput.RGB])


class CameraFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")
    camera_id: str
    scene_id: SceneId
    scene_version: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rgb: bytes | None = None
    depth: bytes | None = None
    segmentation: bytes | None = None
    instance_boxes: list["CameraInstanceBox"] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CameraInstanceBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_object_id: SceneId
    bbox: tuple[int, int, int, int]

    @model_validator(mode="after")
    def valid_box(self):
        y1, x1, y2, x2 = self.bbox
        if not (0 <= y1 < y2 <= 1000 and 0 <= x1 < x2 <= 1000):
            raise ValueError("bbox must be normalized ymin,xmin,ymax,xmax in 0..1000")
        return self

CameraFrame.model_rebuild()
