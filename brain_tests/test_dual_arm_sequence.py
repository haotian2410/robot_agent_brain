import pytest
from robot_agent_brain.planning.atomic_operation_ir import AtomicOperationIR
from robot_agent_brain.planning.dual_arm_sequence import build_commands_sequence


def build(*, second_arm="right", dependencies=(), same_source=False, steps=None):
    operations = [AtomicOperationIR(operation_id="a", kind="pick_and_place", arm="left",
                                    source_object_id=7, destination_object_id=9),
                  AtomicOperationIR(operation_id="b", kind="pick_and_place", arm=second_arm,
                                    source_object_id=7 if same_source else 8,
                                    destination_object_id=9, depends_on=list(dependencies))]
    chains = {operation.operation_id: [
        {"skill_name": "pick", "parameters": {"source": operation.source_object_id}},
        {"skill_name": "put", "parameters": {"destination": 9}}] for operation in operations}
    return build_commands_sequence(operations=operations, skill_steps=chains if steps is None else steps,
        request_id="fixture", scene_id=1, scene_version=2, scene_digest="a" * 64,
        robot_setup_revision=1, skill_contract_revision="fixture-only")


@pytest.mark.parametrize("same_source", [False, True])
def test_shared_objects_add_no_cross_arm_edges(same_source):
    commands = build(same_source=same_source).commands
    assert [command.depends_on for command in commands] == [[], ["L-a-1"], [], ["R-b-1"]]


def test_explicit_operation_edge_targets_only_first_command():
    commands = build(dependencies=["a"]).commands
    assert commands[2].depends_on == ["L-a-2"]
    assert commands[3].depends_on == ["R-b-1"]


def test_single_arm_chains_operations_without_shared_metadata():
    result = build(second_arm="left", dependencies=["a"])
    assert [command.depends_on for command in result.commands] == [[], ["L-a-1"], ["L-a-2"], ["L-b-1"]]
    assert set(result.model_dump()) == {"schema_version", "request_id", "scene_id", "scene_version",
        "scene_digest", "robot_setup_revision", "skill_contract_revision", "commands"}


@pytest.mark.parametrize("dependencies", [["missing"], ["b"], ["a", "a"]])
def test_invalid_operation_dependencies_fail(dependencies):
    with pytest.raises(ValueError, match="commands_v41_dependency_reference_invalid"):
        build(dependencies=dependencies)


@pytest.mark.parametrize("steps", [{}, {"a": [], "b": []}])
def test_operation_coverage_is_validated_against_request(steps):
    with pytest.raises(ValueError, match="commands_v41_operation_coverage_invalid"):
        build(steps=steps)


@pytest.mark.parametrize("field", ["arm", "resource_groups", "hold_constraints", "sync_groups", "depends_on"])
def test_model_cannot_inject_scheduling_into_steps(field):
    steps = {key: [{"skill_name": "pick", "parameters": {}, field: "injected"}] for key in ("a", "b")}
    with pytest.raises(ValueError):
        build(steps=steps)
