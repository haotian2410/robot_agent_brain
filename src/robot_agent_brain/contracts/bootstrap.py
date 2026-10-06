from typing import Literal
from pydantic import BaseModel, ConfigDict, Field
from .scene import SceneConfig


class BootstrapResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene: SceneConfig
    scene_source: Literal["generated"] = "generated"
    entity_candidates: dict[str, list[str]] = Field(default_factory=dict)
    assumptions: list[str] = Field(default_factory=list)
    asset_bindings: dict[str, str] = Field(default_factory=dict)

    def bindings_for(self, scene):
        if (scene.scene_id, scene.scene_version) != (self.scene.scene_id, self.scene.scene_version):
            raise ValueError("bootstrap_binding_version_mismatch")
        return {key: list(value) for key, value in self.entity_candidates.items()}
