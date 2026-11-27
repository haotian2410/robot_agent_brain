"""Negotiated v4 planning: no scene mutation or Control execution."""
from ..contracts.control_skill_contract import ControlSkillContract
from ..contracts.dual_skill_draft import DualSkillDraft
from ..models.dual_operation_planning import DualOperationPlanningRequest
from ..web.protocol import digest as scene_digest
from .atomic_operation_ir import AtomicOperationIR
from .dual_arm_dag import build_negotiated_commands_dag


def require_v4_contract(skill_contract):
    """Fail before camera/assignment work when Control cannot consume v4."""
    if skill_contract is None:
        raise ValueError("unsupported_protocol_version: Control has not advertised dual_arm_sequence_4.1")
    contract = ControlSkillContract.model_validate(skill_contract)
    if "4.1" not in contract.supported_protocols:
        raise ValueError("unsupported_protocol_version: dual_arm_sequence_4.1")
    return contract


def plan_v4(*, request_id, task, scene, profile, revision, runtime,
            skill_contract, provider, recipe, trace):
    contract = require_v4_contract(skill_contract)
    bindings = {e.entity_id: e.scene_object_id for e in task.entities}
    if any(len(e.scene_object_ids) != 1 for e in task.entities):
        raise ValueError("commands_v4_requires_concrete_bindings")
    if (task.scene_id, task.scene_version) != (scene.scene_id, scene.scene_version):
        raise ValueError("command_export_scene_mismatch")
    operations = [AtomicOperationIR(operation_id=op.operation_id, kind=op.task_type.value,
        source_object_id=bindings.get(op.source or op.target),
        destination_object_id=bindings.get(op.destination),
        reference_object_id=bindings.get(op.reference), arm=op.arm,
        depends_on=op.depends_on,
        relation=getattr(op.placement_target, "relation", None)) for op in task.operations]
    request = DualOperationPlanningRequest(scene_id=scene.scene_id, scene_version=scene.scene_version,
        scene_digest=scene_digest(scene), robot_setup_revision=revision,
        robot_setup=profile.setup, runtime=runtime, operations=operations,
        grounded_task=task, skill_contract=contract)
    trace.context = request
    trace.skill_catalog = contract
    if trace.used_planner == "recipe":
        if recipe is None:
            raise ValueError("dual_v4_recipe_not_registered")
        draft = recipe(request)
    else:
        if provider is None or not hasattr(provider, "plan_dual_operations"):
            raise ValueError("dual_v4_qwen_planner_not_configured")
        trace.model_calls += 1
        draft = provider.plan_dual_operations(request)
    draft = DualSkillDraft.model_validate(draft)
    trace.raw_output = draft
    steps = draft.steps_for(op.operation_id for op in operations)
    # Parameter roles come from Control's trusted registry, not skill-name
    # guesses. The model cannot redirect a bound source to another scene ID.
    for operation in operations:
        for step in steps[operation.operation_id]:
            skill = contract.skills.get(step["skill_name"])
            if skill is None:
                raise ValueError("control_skill_unregistered: " + step["skill_name"])
            if skill.object_parameters is None:
                raise ValueError("control_skill_binding_schema_missing: " + step["skill_name"])
            for name, role in skill.object_parameters.items():
                expected = getattr(operation, role)
                if expected is not None and name not in step["parameters"]:
                    raise ValueError("control_skill_object_parameter_missing: " + operation.operation_id + "." + name)
                if name in step["parameters"] and (step["parameters"][name] != expected
                        or type(step["parameters"][name]) is not type(expected)):
                    raise ValueError("commands_v4_object_binding_changed: " + operation.operation_id + "." + name)
    for operation in task.operations:
        contract.validate_operation(operation, steps[operation.operation_id], bindings)
    commands = build_negotiated_commands_dag(skill_contract=contract, draft=draft, operations=operations,
        request_id=request_id, scene_id=scene.scene_id, scene_version=scene.scene_version,
        scene_digest=request.scene_digest, robot_setup_revision=revision)
    contract.validate_commands(commands)
    trace.normalized = commands
    trace.validation = {"status": "validated", "skill_contract_revision": contract.revision}
    return commands
