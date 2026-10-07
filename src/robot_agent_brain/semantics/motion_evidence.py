from __future__ import annotations

import re
from dataclasses import dataclass
from ..contracts.task_intent import Direction, MotionScale

_DIRECTION_PATTERNS = (
    (r"(?:向|往|朝)\s*左\s*(?:移(?:动)?|挪)|左移", Direction.LEFT),
    (r"(?:向|往|朝)\s*右\s*(?:移(?:动)?|挪)|右移", Direction.RIGHT),
    (r"(?:向|往|朝)\s*前\s*(?:移(?:动)?|挪)|前移", Direction.FRONT),
    (r"(?:向|往|朝)\s*后\s*(?:移(?:动)?|挪)|后移", Direction.BACK),
    (r"(?:向|往|朝)\s*上\s*(?:移(?:动)?|挪)|上移", Direction.UP),
    (r"(?:向|往|朝)\s*下\s*(?:移(?:动)?|挪)|下移", Direction.DOWN),
    (r"\b(?:left|leftward|leftwards)\b", Direction.LEFT),
    (r"\b(?:right|rightward|rightwards)\b", Direction.RIGHT),
    (r"\b(?:forward|forwards)\b", Direction.FRONT),
    (r"\b(?:backward|backwards)\b", Direction.BACK),
    (r"\b(?:up|upward|upwards)\b", Direction.UP),
    (r"\b(?:down|downward|downwards)\b", Direction.DOWN),
)
_DISTANCE = re.compile(r"(半|\d+(?:\.\d+)?|[零一二两三四五六七八九十百]+(?:点[零一二两三四五六七八九]+)?)\s*(毫米|mm|厘米|cm|米|m)", re.IGNORECASE)

def _number(text):
    if text == "半":
        return 0.5
    if "点" in text:
        left, right = text.split("点", 1)
        return _number(left) + sum((int(dict(zip("零一二两三四五六七八九", "01223456789"))[c]) * 10 ** -(i + 1)) for i, c in enumerate(right))
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return float(text)
    digits = dict(zip("零一二两三四五六七八九", [0,1,2,2,3,4,5,6,7,8,9]))
    if "百" in text:
        left, right = text.split("百", 1)
        return (digits[left] if left else 1) * 100 + (_number(right) if right else 0)
    if "十" in text:
        left, right = text.split("十", 1)
        return (digits[left] if left else 1) * 10 + (digits[right] if right else 0)
    return digits[text]

@dataclass(frozen=True)
class ExplicitMotionSpan:
    direction: Direction
    distance_m: float | None
    motion_scale: MotionScale | None
    start: int
    end: int

def _extract_motion_spans(instruction: str) -> list[ExplicitMotionSpan]:
    matches = []
    for pattern, direction in _DIRECTION_PATTERNS:
        for match in re.finditer(pattern, instruction, re.IGNORECASE):
            if not any(match.start() < end and match.end() > start for start, end, _ in matches):
                matches.append((match.start(), match.end(), direction))
    matches.sort(key=lambda item: item[0])
    spans = []
    for index, (start, end, direction) in enumerate(matches):
        window_end = matches[index + 1][0] if index + 1 < len(matches) else len(instruction)
        separator = re.search(r"[，,。；;]|然后|再把", instruction[end:window_end])
        if separator:
            window_end = end + separator.start()
        distance_match = _DISTANCE.search(instruction, end, window_end)
        distance = None
        if distance_match:
            distance = _number(distance_match.group(1))
            if distance_match.group(2).casefold() in {"毫米", "mm"}:
                distance /= 1000.0
            elif distance_match.group(2).casefold() in {"厘米", "cm"}:
                distance /= 100.0
        phrase = instruction[max(0, start - 4):window_end].casefold()
        scale = None
        if distance is None and any(token in phrase for token in ("大幅", "很多", "很远", "a lot", "far")):
            scale = MotionScale.LARGE
        elif distance is None and any(token in phrase for token in ("一些", "一段", "适中", "远一些", "some", "moderately")):
            scale = MotionScale.MEDIUM
        elif distance is None and any(token in phrase for token in ("一点", "稍微", "轻微", "远一点", "a little", "slightly")):
            scale = MotionScale.SMALL
        spans.append(ExplicitMotionSpan(direction, distance, scale, start, distance_match.end() if distance_match else end))
    return spans



def resolve_motion_evidence(instruction, operation_count):
    """Bind motion evidence in clause order; never broadcast a distance."""
    spans = _extract_motion_spans(instruction)
    if len(spans) != operation_count:
        raise ValueError("motion_clause_binding_ambiguous")
    if any(span.distance_m is None and span.motion_scale is None for span in spans):
        raise ValueError("motion_distance_evidence_missing")
    return spans


def normalize_scene_motion(instruction, edit):
    from ..contracts.turn import SceneEditIntent
    operations = edit.operations
    count = sum(op.operation == "translate" for op in operations)
    if not count:
        return edit
    evidence = iter(resolve_motion_evidence(instruction, count))
    result = []
    for operation in operations:
        if operation.operation != "translate":
            result.append(operation)
            continue
        span = next(evidence, None)
        values = operation.model_dump()
        if span is not None:
            values["direction"] = span.direction
            if span.distance_m is not None or span.motion_scale is not None:
                values.update(distance_m=span.distance_m, motion_scale=span.motion_scale)
        result.append(SceneEditIntent.model_validate(values))
    return edit.model_copy(update={"operations": result})
