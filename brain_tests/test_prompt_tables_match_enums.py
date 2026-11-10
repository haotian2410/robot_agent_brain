"""The generated spatial tables must match the live contracts, not a copy."""

import re

from robot_agent_brain.contracts.spatial import (BINARY_SPATIAL_RELATIONS, EXTREME_SPATIAL_RELATIONS,
                                                 HALF_SPATIAL_RELATIONS, PLACEMENT_HINTS,
                                                 PLACEMENT_TARGET_KINDS, RelationScope,
                                                 SpatialRelationType, TABLETOP_REGIONS,
                                                 UNARY_SPATIAL_RELATIONS)
from robot_agent_brain.contracts.turn import SceneLayoutRelation, SceneQueryIntent
from robot_agent_brain.models.prompts import (TASK_UNDERSTANDING_PROMPT, _literal_values,
                                              build_spatial_reference_tables)


def test_spatial_tables_cover_every_contract_value():
    tables = build_spatial_reference_tables()
    for relation in SpatialRelationType:
        assert relation.value in tables
    for region in TABLETOP_REGIONS:
        assert f"`{region}`" in tables
    for kind in PLACEMENT_TARGET_KINDS:
        assert kind in tables
    for hint in PLACEMENT_HINTS:
        assert hint in tables
    for scope in RelationScope:
        assert scope.value in tables
    for relation in SceneLayoutRelation:
        assert relation.value in tables


def _values(line: str) -> set[str]:
    return set(line.split("：", 1)[1].rstrip("。").split("、"))


def test_reference_rules_are_documented_per_relation_family():
    tables = build_spatial_reference_tables()
    halves_line = re.search(r"- 半区关系（.*?。", tables, re.S).group(0)
    extremes_line = re.search(r"- 极值关系（.*?。", tables, re.S).group(0)
    binary_line = re.search(r"- 二元关系（.*?。", tables, re.S).group(0)
    assert _values(halves_line) == set(HALF_SPATIAL_RELATIONS)
    assert _values(extremes_line) == set(EXTREME_SPATIAL_RELATIONS)
    assert _values(binary_line) == {relation.value for relation in BINARY_SPATIAL_RELATIONS}
    assert _values(halves_line) | _values(extremes_line) == {relation.value for relation in UNARY_SPATIAL_RELATIONS}


def test_query_predicate_table_matches_the_contract():
    tables = build_spatial_reference_tables()
    predicate_line = re.search(r"- `scene_query\.predicate` 取值：.*?。", tables, re.S).group(0)
    declared = _literal_values(SceneQueryIntent.model_fields["predicate"].annotation)
    assert _values(predicate_line) == {str(value) for value in declared}


def test_generated_tables_never_contradict_the_route_rules():
    assert "relations" in TASK_UNDERSTANDING_PROMPT
    assert "lexicon" not in TASK_UNDERSTANDING_PROMPT.casefold()
    assert "route_selection.txt" not in TASK_UNDERSTANDING_PROMPT
    assert TASK_UNDERSTANDING_PROMPT.count("## 附录：空间语义取值表") == 1


def test_region_aliases_come_from_the_shared_phrase_table():
    from robot_agent_brain.semantics import spatial_phrases
    tables = build_spatial_reference_tables()
    for phrases, region in spatial_phrases.TABLETOP_REGION_PHRASES:
        for phrase in phrases:
            assert phrase in tables
