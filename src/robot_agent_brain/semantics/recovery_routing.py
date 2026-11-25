"""Finite supplements that need R, not an independent-task U preview.

This is an optimization hint, not a parser or permission to execute anything.
Unknown phrases retain the existing preview path.
"""
import re


_ACTION_WORDS = (
    "增加", "添加", "生成", "放置", "放到", "放进", "移动", "挪到", "拿起",
    "抓起", "抓取", "放下", "删除", "移除", "改成", "换成", "旋转", "缩放",
    "打开", "关闭", "拉开", "推回", "查询", "有几个", "是否存在", "找出",
    "put", "pick", "move", "delete", "open", "close", "query",
)


def independent_task_candidate(text: str, *, asset_names=()) -> bool:
    """Conservatively identify a complete current task before failure recovery.

    This is routing only; normal understanding remains the authority on whether
    the task is valid.  It intentionally rejects short amendments such as
    ``改成蓝色`` and selectors, while accepting explicit actions with an asset
    noun or an ordered compound instruction.
    """
    value = text.strip().rstrip("。！？!?，, ")
    if not value or continuation_candidate(value, asset_names=asset_names):
        return False
    has_action = any(word in value for word in _ACTION_WORDS)
    if not has_action:
        return False
    names = {str(name).lower() for name in asset_names if name}
    lowered = value.lower()
    has_asset = any(name and name in lowered for name in names)
    compound = any(marker in value for marker in ("先", "然后", "接着", "之后", "再", "并把", "并将", "并让", ";", "；"))
    # A compound with explicit actions is a complete task even if the asset
    # catalog does not know one noun; normal U must report that asset error.
    return (compound and sum(1 for word in _ACTION_WORDS if word in value) >= 2) or (has_action and has_asset)


def continuation_candidate(text: str, *, asset_names=()) -> bool:
    text = text.strip().rstrip("。！？!?，, ")
    if text in {
        "左边的", "左边那个", "右边的", "右边那个",
        "前面的", "前面那个", "后面的", "后面那个",
        "第一个", "第二个", "第三个", "就是它", "那个",
        "红色的", "蓝色的", "绿色的", "黄色的", "黑色的", "白色的",
        "两个都要", "算了", "取消", "哪个我也不知道",
    }:
        return True
    if re.fullmatch(r"ID\s*[0-9]+\s*的", text, re.IGNORECASE):
        return True
    # These identify/revise a slot but contain no independent action. In
    # particular, U can interpret "最左边那个苹果" as a selection query; that
    # must not supersede the pending pick/place task before R sees it.
    selector = r"(?:最)?(?:左|右|前|后)(?:边|面|侧)?(?:的|那个|那只)?(?:苹果|香蕉|篮子|托盘|物体|对象)?"
    if re.fullmatch(selector, text):
        return True
    # Catalog names only extend the noun slot; arbitrary actions or query
    # phrases cannot match this fully anchored selector grammar.
    names = sorted({str(name) for name in asset_names if name}, key=len, reverse=True)
    if names:
        noun = "(?:" + "|".join(re.escape(name) for name in names) + ")"
        if re.fullmatch(r"(?:最)?(?:左|右|前|后)(?:边|面|侧)?(?:的|那个|那只)?" + noun, text):
            return True
    if re.fullmatch(r"(?:object_?id|对象编号)\s*[:=]?\s*\d+", text, re.IGNORECASE):
        return True
    if re.fullmatch(r"(?:不对[，,]?|不是[，,]?)?(?:改成|换成)" + selector, text):
        return True
    if re.fullmatch(r"(?:那)?(?:两个|两只|2个)(?:苹果|香蕉|物体|对象)?(?:都要|都放)", text):
        return True
    if re.fullmatch(r"(?:换成|不是.+[，,]是)(?:篮子|托盘|杯子)", text):
        return True
    return False
