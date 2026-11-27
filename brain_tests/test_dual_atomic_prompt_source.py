from robot_agent_brain.models.prompts import (
    build_atomic_skill_prompt, build_dual_atomic_skill_prompt,
    build_atomic_draft_output_rules,
)


def test_single_and_dual_share_control_source_with_distinct_output_envelopes(tmp_path):
    source = tmp_path / "skill.md"
    source.write_text("Control reviewed skill specification: fixture only", encoding="utf-8")
    single, single_sha = build_atomic_skill_prompt(source)
    dual, dual_sha = build_dual_atomic_skill_prompt(source)
    assert single_sha == dual_sha and single_sha is not None
    assert source.read_text() in single and source.read_text() in dual
    assert build_atomic_draft_output_rules() in single
    assert build_atomic_draft_output_rules() not in dual
    assert '"operations"' in dual and '"steps"' in dual
    assert "stages" not in dual


def test_package_has_no_retired_staged_prompt():
    from importlib.resources import files
    assert not files("robot_agent_brain.models").joinpath(
        "prompt_templates", "dual_skill_planning_v3.txt").is_file()
