"""Validate actual wire actions, not just first-stage parallel hints."""


def validate_dual_capability(commands, profile):
    if profile.commands_version != "3.0" or profile.setup.mode != "dual":
        raise ValueError("execution_commands_version_mismatch")
    if set(profile.setup.arms) != set(commands.robot_setup.arms):
        raise ValueError("execution_robot_setup_mismatch")
    for side, binding in commands.robot_setup.arms.items():
        declared = profile.setup.arms[side]
        if any(getattr(binding, key) != getattr(declared, key)
               for key in ("planning_group", "end_effector", "gripper")):
            raise ValueError("execution_robot_setup_mismatch")
    if not profile.coordinated_execution and any(
            step.arms.left is not None and step.arms.right is not None for step in commands.steps):
        raise ValueError("dual_coordinated_execution_not_registered")
    if any(cmd.skill_name.value not in profile.supported_skills for step in commands.steps
           for cmd in (step.arms.left, step.arms.right) if cmd is not None):
        raise ValueError("dual_profile_skill_unsupported")
