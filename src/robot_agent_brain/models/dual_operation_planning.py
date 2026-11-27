"""Bound v4 skill input; model owns chains, not identity or scheduling."""
from pydantic import BaseModel, ConfigDict, Field, model_validator
from ..contracts.control_skill_contract import ControlSkillContract
from ..contracts.robot_setup import RobotRuntimeState, RobotSetup
from ..planning.atomic_operation_ir import AtomicOperationIR
from ..contracts.grounded_task import GroundedTask


class DualOperationPlanningRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scene_id: int = Field(ge=0)
    scene_version: int = Field(ge=0)
    scene_digest: str = Field(min_length=1)
    robot_setup_revision: int = Field(ge=0)
    robot_setup: RobotSetup
    runtime: RobotRuntimeState
    operations: list[AtomicOperationIR] = Field(min_length=1)
    grounded_task: GroundedTask
    skill_contract: ControlSkillContract

    @model_validator(mode="after")
    def bound_and_supported(self):
        if (self.scene_id, self.scene_version) != (
                self.grounded_task.scene_id, self.grounded_task.scene_version):
            raise ValueError("dual_operation_scene_binding_mismatch")
        expected = {op.operation_id: op for op in self.grounded_task.operations}
        if [op.operation_id for op in self.operations] != [op.operation_id for op in self.grounded_task.operations]:
            raise ValueError("commands_v41_operation_coverage_invalid")
        bindings = {entity.entity_id: entity.scene_object_id for entity in self.grounded_task.entities}
        for operation in self.operations:
            semantic = expected[operation.operation_id]
            if (operation.kind != semantic.task_type.value or operation.arm != semantic.arm
                    or operation.depends_on != semantic.depends_on
                    or operation.source_object_id != bindings.get(semantic.source or semantic.target)
                    or operation.destination_object_id != bindings.get(semantic.destination)
                    or operation.reference_object_id != bindings.get(semantic.reference)):
                raise ValueError("dual_operation_semantic_binding_mismatch")
        if self.robot_setup.mode != "dual" or set(self.runtime.arms) != {"left", "right"}:
            raise ValueError("dual_operation_planning_requires_dual")
        if any(not state.state_known for state in self.runtime.arms.values()):
            raise ValueError("robot_runtime_state_unknown")
        if any(operation.arm not in {"left", "right"} for operation in self.operations):
            raise ValueError("commands_v4_arm_assignment_missing")
        ids = [operation.operation_id for operation in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("commands_v4_duplicate_operation")
        if "4.1" not in self.skill_contract.supported_protocols:
            raise ValueError("unsupported_protocol_version: dual_arm_sequence_4.1")
        return self
