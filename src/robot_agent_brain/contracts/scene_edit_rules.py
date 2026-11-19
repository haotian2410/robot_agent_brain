"""Shared edit field rules; full-mode compatibility remains in SceneEditIntent.

Wire objects are closed per operation. Unlike full historical payloads, they
must omit inapplicable fields even when their value is null or a default.
"""
LAYOUT_OPERATIONS = frozenset({"add", "move_relative", "update"})
PROPERTY_OPERATIONS = frozenset({"add", "update", "update_properties"})
FRAME_OPERATIONS = frozenset({"translate", "rotate"})
MOTION_FIELDS = frozenset({"relation", "reference", "direction", "distance_m", "motion_scale", "axis", "angle_deg"})
SCALE_FIELDS = ("scale_mode", "scale_xyz", "scale_direction", "scale_amount")
SCALE_MODES = (("scale_mode", "scale_xyz"), ("scale_direction", "scale_amount"))
DISTANCE_FIELDS = ("distance_m", "motion_scale")
RELATION_PAIR = ("relation", "reference")
MOTION_ALLOWED = {
    "add": frozenset(RELATION_PAIR), "remove": frozenset(), "replace": frozenset(),
    "translate": frozenset({"direction", *DISTANCE_FIELDS}),
    "move_relative": frozenset(RELATION_PAIR),
    "rotate": frozenset({"axis", "angle_deg"}), "orient": frozenset(),
    "update_properties": frozenset(), "scale": frozenset(),
    "update": frozenset(RELATION_PAIR),
}
REQUIRED = {
    "rotate": ("axis", "angle_deg"), "replace": ("replacement_entity",),
    "orient": ("posture",), "translate": ("direction",),
    "move_relative": RELATION_PAIR,
}
COMMON_FIELDS = frozenset({"operation", "target", "operation_id", "depends_on", "explicit_robot"})


def wire_fields(operation):
    fields = set(COMMON_FIELDS | MOTION_ALLOWED[operation])
    fields.update(REQUIRED.get(operation, ()))
    if operation in LAYOUT_OPERATIONS:
        fields.update(("placement_hint", "placement_region", "placement_goal"))
    if operation in PROPERTY_OPERATIONS:
        fields.add("properties")
    if operation in FRAME_OPERATIONS:
        fields.add("coordinate_frame")
    if operation == "rotate":
        fields.add("pivot")
    if operation == "scale":
        fields.update(SCALE_FIELDS)
    return fields
