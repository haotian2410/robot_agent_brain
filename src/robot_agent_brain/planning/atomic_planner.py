"""Assemble the control atomic-skill command document for a single-arm task.

The Brain no longer translates its semantic skills at the export boundary: this
module produces the control document directly, either from the deterministic
assembly graph or from the planning round that answers with it.
"""
from __future__ import annotations

from ..contracts.commands_atomic import (ApproachParameters, AtomicCommand, AtomicCommandsFile,
                                         AtomicSkillName, LiftUpParameters,
                                         PickParameters, PullPushParameters, PutParameters, RetreatParameters)
from ..contracts.grounded_task import GroundedTask
from ..contracts.scene import SceneConfig
from ..contracts.task_intent import TaskType
from ..errors import BrainError
from ..models.qwen_http import QwenProviderError
from .atomic_plan_validator import AtomicPlanValidator
from .context_builder import build_planner_context
from .skill_planner_router import PlanningTrace

# The control grammar has no perception-only step and no press, so a semantic
# move/locate/press turn cannot be mapped without inventing behaviour.  Drawer
# strokes can be: skill.md's 开关抽屉 graph is approach + pick + pull/push + retreat.
SUPPORTED_TASK_TYPES = frozenset({TaskType.GRASP, TaskType.RELEASE, TaskType.PICK_AND_PLACE,
                                  TaskType.OPEN, TaskType.CLOSE})
# skill.md's own drawer stroke. ``frame: grasp`` is the only frame the Brain may
# assume -- it has no access to the drawer's pose, so it cannot name a world
# direction the way the control's hand-written example does.
DRAWER_STROKE = {"distance": 0.16, "frame": "grasp"}


def expand_atomic_plan(task: GroundedTask, held_object=None) -> list[AtomicCommand]:
    """Deterministic assembly graph for the operations control can execute."""
    object_id = {entity.entity_id: entity.scene_object_id for entity in task.entities}
    commands: list[AtomicCommand] = []
    held = held_object

    def add(skill, parameters):
        commands.append(AtomicCommand(command_id=str(len(commands) + 1), skill_name=skill,
                                      parameters=parameters))

    def grasp(object_id_value):
        add(AtomicSkillName.APPROACH, ApproachParameters(target=object_id_value))
        add(AtomicSkillName.PICK, PickParameters(target=object_id_value))
        add(AtomicSkillName.LIFT_UP, LiftUpParameters())
        add(AtomicSkillName.RETREAT, RetreatParameters(target=object_id_value))

    def place(object_id_value):
        add(AtomicSkillName.APPROACH, ApproachParameters(target=object_id_value))
        add(AtomicSkillName.PUT, PutParameters(target=object_id_value))
        add(AtomicSkillName.RETREAT, RetreatParameters(target=object_id_value))

    def stroke(object_id_value, *, push):
        add(AtomicSkillName.APPROACH, ApproachParameters(target=object_id_value))
        add(AtomicSkillName.PICK, PickParameters(target=object_id_value))
        add(AtomicSkillName.PUSH if push else AtomicSkillName.PULL, PullPushParameters(**DRAWER_STROKE))
        add(AtomicSkillName.RETREAT, RetreatParameters(target=object_id_value))

    for operation in task.operations:
        if operation.task_type == TaskType.PICK_AND_PLACE:
            source, destination = object_id[operation.source], object_id[operation.destination]
            if source != held:
                grasp(source)
                held = source
            place(destination)
            held = None
        elif operation.task_type == TaskType.GRASP:
            source = object_id[operation.target or operation.source]
            if source != held:
                grasp(source)
                held = source
        elif operation.task_type in {TaskType.OPEN, TaskType.CLOSE}:
            if held is not None:
                raise BrainError("atomic_plan_gripper_occupied", "skill_planning",
                                 "推拉之前夹爪必须为空，请先放下所持物体")
            grip = operation.reference if operation.reference in object_id else operation.target
            stroke(object_id[grip], push=operation.task_type is TaskType.CLOSE)
            # The control releases the handle at the end of the stroke.
            held = None
        else:
            destination = object_id.get(operation.reference or "")
            if held is None or destination is None:
                raise BrainError("atomic_capability_unsupported", "skill_planning",
                                 "release 需要已夹持的物体和一个明确的放置参照")
            place(destination)
            held = None
    return commands


class AtomicPlanner:
    """Route a grounded task to the control dialect, deterministically or via Qwen."""

    def __init__(self, *, mode: str, provider=None):
        if mode not in {"recipe", "qwen", "auto"}:
            raise ValueError("planner_mode_invalid")
        self.mode, self.provider = mode, provider
        self.last_trace: PlanningTrace | None = None

    def plan(self, request_id: str, task: GroundedTask, scene: SceneConfig, *,
             held_object=None) -> AtomicCommandsFile:
        trace = self.last_trace = PlanningTrace(self.mode)
        try:
            unsupported = [op.task_type.value for op in task.operations
                           if op.task_type not in SUPPORTED_TASK_TYPES]
            if unsupported:
                # Reject before any model call: the control grammar cannot
                # express these, and a stretched mapping would report success
                # for an action the robot never performed.
                raise BrainError("atomic_capability_unsupported", "skill_planning",
                                 "控制端原子技能无法表达: " + ",".join(sorted(set(unsupported))))
            if self.mode == "qwen":
                commands = self._plan_with_model(request_id, task, scene, trace, held_object)
            else:
                trace.used_planner = "recipe"
                commands = self._envelope(request_id, scene, expand_atomic_plan(task, held_object))
                # The guard is the contract, not a model-output audit, and it is
                # also what puts a requested side offset onto the export.
                commands = AtomicPlanValidator().validate(commands, task, scene, held_object=held_object)
            trace.normalized = commands
            trace.validation = {"valid": True, "scope": "atomic_assembly"}
            return commands
        except Exception as exc:
            trace.validation = {"valid": False, "error": f"{type(exc).__name__}: {exc}"}
            if isinstance(exc, BrainError):
                raise
            # A model-output failure keeps its precise code so the UI can point at
            # the offending command; only transport problems degrade to the
            # generic planning failure.
            if isinstance(exc, QwenProviderError) and exc.code != "provider_error":
                code = exc.code
            else:
                code = "skill_planning_failed"
            raise BrainError(code, "skill_planning",
                             f"{type(exc).__name__}: {exc}") from exc

    def _plan_with_model(self, request_id, task, scene, trace, held_object):
        if self.provider is None or not hasattr(self.provider, "plan_atomic"):
            raise BrainError("skill_planning_provider_missing", "skill_planning",
                             "Provider has no atomic planning interface")
        trace.used_planner = "qwen"
        trace.context = build_planner_context(task, held_object)
        validator = AtomicPlanValidator()
        calls = getattr(self.provider, "calls", [])

        def finalize(draft_commands):
            # command_id only labels the array for reporting; the Brain owns the
            # sequential numbering so feedback rows always match the export.
            ordered = [command.model_copy(update={"command_id": str(index)})
                       for index, command in enumerate(draft_commands, 1)]
            return self._envelope(request_id, scene, ordered)

        # The guard runs on the exact document that will be exported, inside the
        # provider call, so a violation costs one repair turn instead of a
        # Python-side completion.
        def validate(draft):
            validator.validate(finalize(draft.commands), task, scene, held_object=held_object)

        before = len(calls)
        # Count the attempt that is about to happen, so a timeout still reports
        # the call it made instead of pretending the stage never ran.
        trace.model_calls = 1
        draft = self.provider.plan_atomic(trace.context, validate=validate)
        trace.model_calls = max(len(calls) - before, 1)
        trace.raw_output = getattr(self.provider, "last_raw_values", {}).get(
            "skill_planning", draft.model_dump(mode="json"))
        # Run the guard once more for its return value: it pins every ``put``
        # offset onto the landing the task declared, and the document it hands
        # back is the one that ships.
        return validator.validate(finalize(draft.commands), task, scene, held_object=held_object)

    @staticmethod
    def _envelope(request_id, scene, commands):
        return AtomicCommandsFile(request_id=request_id, scene_id=scene.scene_id,
                                  scene_version=scene.scene_version, commands=commands)
