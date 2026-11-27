import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("layout_smoke", Path(__file__).resolve().parents[1]
                                           / "scripts" / "smoke_layout_qwen.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
shape_matches = module.shape_matches


def test_smoke_oracle_rejects_screen_coordinate_inversions():
    assert shape_matches(1, [(0, .5), (1, .5)])
    assert not shape_matches(1, [(0, .5), (1, .6)])
    assert shape_matches(2, [(.2, .8), (.5, .2), (.8, .8)])
    assert not shape_matches(2, [(.2, .2), (.5, .8), (.8, .2)])
    assert shape_matches(3, [(.1, .8), (.9, .8), (.1, .2), (.9, .2)])
    assert not shape_matches(3, [(.1, .2), (.9, .2), (.1, .8), (.9, .8)])
