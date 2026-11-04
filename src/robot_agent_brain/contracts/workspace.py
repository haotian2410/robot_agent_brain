"""Typed tabletop semantics included in every live understanding request."""
from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSemanticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: str = Field(default="tabletop", pattern="^tabletop$")
    interaction_mode: str = Field(default="tabletop_edit", pattern="^tabletop_edit$")
    default_support: str = "primary_table"
    coordinate_convention: str = Field(default="x_right_y_front_z_up", pattern="^x_right_y_front_z_up$")
    table_external_placement: bool = False
    semantics_version: str = "tabletop.v1"
