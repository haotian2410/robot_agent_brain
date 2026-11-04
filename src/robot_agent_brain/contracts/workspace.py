"""Typed tabletop semantics included in every live understanding request."""
from pydantic import BaseModel, ConfigDict, Field


class WorkspaceSemanticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: str = Field(default="tabletop", pattern="^tabletop$")
    interaction_mode: str = Field(default="tabletop_edit", pattern="^tabletop_edit$")
    default_support: str = "primary_table"
    # Optional verified OLS identity for the support surface. A semantic
    # name such as ``table`` alone is insufficient for an uploaded Scene v1:
    # it could be a prop, a duplicate table, or an untrusted surface. The
    # Brain binds this reference from configuration and reports the concrete
    # scene object separately in scene_context.
    primary_table_metadata_ref: str | None = None
    coordinate_convention: str = Field(default="x_right_y_front_z_up", pattern="^x_right_y_front_z_up$")
    table_external_placement: bool = False
    semantics_version: str = "tabletop.v1"
