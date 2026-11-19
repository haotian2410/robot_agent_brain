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
    return re.fullmatch(r"ID\s*[0-9]+\s*的", text, re.IGNORECASE) is not None
