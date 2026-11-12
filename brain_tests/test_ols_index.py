"""Both published index generations must normalize to the same view."""
import pytest

from robot_agent_brain.adapters.ols_index import hidden_ids, index_by_id


ARRAY = [
    {"id": 1, "name": "ur5_table_empty", "task_category": "空白", "no_display": False},
    {"id": 2, "name": "ur5_table_apple", "task_category": "抓取", "no_display": True},
]
OBJECT = {
    "by_name": {"ur5_table_empty": 1, "ur5_table_apple": 2},
    "by_id": {"1": "ur5_table_empty", "2": "ur5_table_apple"},
    "category": {"1": "table"},
    "no_display": {"1": False, "2": True},
}


@pytest.mark.parametrize("index", [ARRAY, OBJECT])
def test_both_shapes_yield_the_same_ids_names_and_hidden_set(index):
    assert index_by_id(index) == {1: "ur5_table_empty", 2: "ur5_table_apple"}
    assert hidden_ids(index) == {2}


def test_a_missing_no_display_only_hides_nothing():
    assert hidden_ids([{"id": 3, "name": "mug"}]) == set()
    assert hidden_ids({"by_id": {"3": "mug"}}) == set()


@pytest.mark.parametrize("index", [
    [{"id": "1", "name": "ur5_table_empty"}],
    [{"id": 1}],
    "ur5_table_empty",
    {"by_id": {"1": 1}},
    {},
])
def test_an_unrecognized_or_broken_entry_is_refused(index):
    with pytest.raises(ValueError, match="ols_index_"):
        index_by_id(index)
