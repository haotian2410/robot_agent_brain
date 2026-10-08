from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .scene import SceneId
from .turn import TurnKind, TurnStatus
from ..errors import BrainIssue


class BrainRunReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    report_version: Literal["1.0"] = "1.0"
    session_id: str
    request_id: str
    turn_kind: TurnKind | None = None
    turn_status: TurnStatus | None = None
    run_status: Literal["success", "blocked", "failed"]
    delivery_status: str = "none"
    scene_source: Literal["uploaded", "session", "generated", "none"] = "none"
    scene_created: bool = False
    scene_id: SceneId | None = None
    scene_version: int | None = None
    scene_commit_status: Literal["unchanged", "committed", "unknown"] = "unchanged"
    executed: Literal[False] = False
    reply: str = ""
    provider: str
    artifacts: dict[str, str] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    metrics: dict = Field(default_factory=dict)
    error: BrainIssue | None = None
