import importlib.util
from pathlib import Path

spec=importlib.util.spec_from_file_location("analyze_perf",Path(__file__).parents[1]/"scripts/analyze_perf_trace.py")
module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def record(identifier,name,start,end,parent=None):
    return dict(type="span",trace_id="t",span_id=identifier,parent_span_id=parent,
                name=name,start_ns=int(start*1e9),end_ns=int(end*1e9),source="fixture:function")


def test_parallel_children_do_not_double_count_wall_time():
    summary,rows,_=module.analyze([record("p","parent",0,3),record("a","a",0,2,"p"),record("b","b",1,3,"p")])
    assert summary["wall_time_partition_ms"]=={"a":1000,"concurrent:a+b":1000,"b":1000}
    assert len(rows)==3
    assert sum(summary["wall_time_partition_ms"].values())==summary["observed_window_ms"]


def test_gap_is_explicit_and_fractional_seconds_are_not_rounded_to_full_second():
    summary,rows,slices=module.analyze([record("a","a",0,.1),record("b","b",1.2,1.3)])
    assert summary["wall_time_partition_ms"]["unattributed"]==1100
    assert len(summary["unattributed_over_500ms"])==1
    assert len(rows)==2


def test_duplicate_ids_are_rejected():
    import pytest
    with pytest.raises(ValueError,match="duplicate_span_id"):
        module.analyze([record("a","a",0,1),record("a","a",0,1)])
