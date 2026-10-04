from enum import StrEnum
from pydantic import BaseModel, ConfigDict


class TurnKind(StrEnum):
    ROBOT_TASK = "robot_task"
    SCENE_EDIT = "scene_edit"
    SCENE_QUERY = "scene_query"
    SESSION_CONTROL = "session_control"


class BrainTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    turn_kind: TurnKind
    instruction: str

