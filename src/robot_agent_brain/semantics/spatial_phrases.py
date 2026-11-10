"""One tabletop-phrase vocabulary shared by normalization and prompting.

The provider is asked to emit canonical region tokens, but it still often
answers corner wording with a bare ``direction``.  Both the deterministic
normalizer and the generated prompt tables must read the same phrases,
otherwise the prompt can ask for a token Python refuses to infer.
"""

# Ordered by precedence: an explicit corner wins over a half/compass phrase.
TABLETOP_REGION_PHRASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("左上角", "左上方", "左前角", "左前方"), "left_front"),
    (("右上角", "右上方", "右前角", "右前方"), "right_front"),
    (("左下角", "左下方", "左后角", "左后方"), "left_back"),
    (("右下角", "右下方", "右后角", "右后方"), "right_back"),
    (("东北角", "东北方", "右上"), "right_front"),
    (("西北角", "西北方", "左上"), "left_front"),
    (("东南角", "东南方", "右下"), "right_back"),
    (("西南角", "西南方", "左下"), "left_back"),
    (("右侧", "右边", "东侧", "东边"), "right_half"),
    (("左侧", "左边", "西侧", "西边"), "left_half"),
    (("前侧", "前方", "北侧", "北边"), "front_half"),
    (("后侧", "后方", "南侧", "南边"), "back_half"),
)
TABLETOP_CENTER_PHRASES: tuple[str, ...] = ("中间", "正中央", "中心位置")
OBJECT_RELATIVE_PHRASES: tuple[str, ...] = (
    "旁边", "附近", "靠近", "最近", "最远", "左边", "右边", "左侧", "右侧",
    "前面", "后面", "前方", "后方", "上面", "下面", "里面", "内", "放进",
    "near", "nearest", "farthest", "left of", "right of", "behind", "inside",
)
TABLE_PHRASES: tuple[str, ...] = ("桌", "桌面", "台面", "table", "desktop", "work table")
TABLE_REFERENCE_TOKENS = frozenset({
    "table", "desk", "desktop", "work_table", "桌子", "桌面", "台面",
})


def match_tabletop_region(text: str) -> tuple[str, bool] | None:
    """Return ``(region, hard_center)`` for already-casefolded instruction text."""
    for phrases, region in TABLETOP_REGION_PHRASES:
        if any(phrase in text for phrase in phrases):
            return region, False
    if any(phrase in text for phrase in TABLETOP_CENTER_PHRASES):
        return "center", True
    return None


def has_object_relative_language(text: str) -> bool:
    return any(phrase in text for phrase in OBJECT_RELATIVE_PHRASES)


def references_table(text: str) -> bool:
    return any(phrase in text for phrase in TABLE_PHRASES)
