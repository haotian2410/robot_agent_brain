from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field


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
    scene_id: str
    scene_version: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    rgb: bytes | None = None
    depth: bytes | None = None
    segmentation: bytes | None = None
    instance_boxes: list["CameraInstanceBox"] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class CameraInstanceBox(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_object_id: str
    bbox: tuple[int, int, int, int]
