"""Typed tabletop semantics included in every live understanding request."""
from typing import Literal

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
    # These fields make the tabletop contract explicit in every request and
    # in persisted diagnostics.  Geometry still comes from the verified Scene
    # and LayoutDefaults; these values describe the semantic convention, not
    # an instruction to invent coordinates.
    workspace_center_m: tuple[float, float] | None = None
    default_plane: Literal["xy"] = "xy"
    default_rotation_axis: Literal["z"] = "z"
    placement_policy_version: str = "grid-v2"
    motion_policy_version: str = "motion-v1"
    semantics_version: str = "tabletop.v1"
