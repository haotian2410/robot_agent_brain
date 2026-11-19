"""Finite supplements that need R, not an independent-task U preview.

This is an optimization hint, not a parser or permission to execute anything.
Unknown phrases retain the existing preview path.
"""
import re


def continuation_candidate(text: str) -> bool:
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
    if re.fullmatch(r"(?:不对[，,]?|不是[，,]?)?(?:改成|换成)" + selector, text):
        return True
    if re.fullmatch(r"(?:那)?(?:两个|两只|2个)(?:苹果|香蕉|物体|对象)?(?:都要|都放)", text):
        return True
    if re.fullmatch(r"(?:换成|不是.+[，,]是)(?:篮子|托盘|杯子)", text):
        return True
    return False
