"""Reject loss of explicit numeric constraints; never repair model output."""
import math
import re

_DIGITS = dict(zip("零〇一二两三四五六七八九", (0, 0, 1, 2, 2, 3, 4, 5, 6, 7, 8, 9)))
_NUMBER = r"[0-9零〇一二两三四五六七八九十百千万点.]+"
_COPULA = r"\s*(?:(?:固定)?(?:为|是)|(?:is\s+)?(?:fixed\s+at)|is|=|:|：)?\s*"
_LENGTH_UNIT = r"毫米|厘米|米|mm\b|cm\b|m\b"
_METERS = {"毫米": .001, "厘米": .01, "米": 1, "mm": .001, "cm": .01, "m": 1}


def _number(token):
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", token):
        return float(token)
    if token in _DIGITS:
        return float(_DIGITS[token])
    if re.fullmatch(r"[一二两三四五六七八九]?十[一二三四五六七八九]?", token):
        tens, ones = token.split("十")
        return float(_DIGITS.get(tens, 1) * 10 + _DIGITS.get(ones, 0))
    raise ValueError("scene_layout_explicit_spacing_number_unsupported")


def validate_explicit_spacing(instruction, spec):
    # Deliberately limited to unambiguous numeric center/edge-distance expressions.
    # Other phrases still require semantic understanding, not guessed numbers.
    matches = re.findall(
        r"(中心间距|边缘间距|center(?:[- ]to[- ]center)?\s+spacing|edge(?:[- ]to[- ]edge)?\s+spacing)"
        + _COPULA + f"({_NUMBER})\\s*({_LENGTH_UNIT})",
        instruction, re.IGNORECASE)
    for label, value, unit in matches:
        meters = _number(value) * _METERS[unit.lower()]
        spacing = spec.spacing
        mode = "edge" if label.startswith("边缘") or label.lower().startswith("edge") else "center"
        if (spacing.mode != mode or spacing.auto or spacing.value_m is None
                or not math.isclose(spacing.value_m, meters, rel_tol=1e-9, abs_tol=1e-12)):
            raise ValueError("scene_layout_explicit_spacing_mismatch")


def validate_explicit_pattern_dimensions(instruction, spec):
    """Check explicitly named pattern dimensions, without inferring absent ones.

    This narrow guard is not a general natural-language parser. An unsupported
    numeric expression is refused rather than guessed; model values are never
    repaired. Longest labels are matched together so an inner/outer radius is
    never accidentally interpreted as the generic circle radius.
    """
    labels = {"内半径": "inner_radius_m", "外半径": "outer_radius_m", "半径": "radius_m",
              "inner radius": "inner_radius_m", "outer radius": "outer_radius_m",
              "radius": "radius_m", "弧角": "angle_span_deg", "圆心角": "angle_span_deg",
              "arc angle": "angle_span_deg"}
    pattern = r"(内半径|外半径|半径|inner\s+radius|outer\s+radius|\bradius|弧角|圆心角|arc\s+angle)"
    pattern += _COPULA + f"({_NUMBER})\\s*({_LENGTH_UNIT}|度|degrees?\\b|°)"
    for label, value, unit in re.findall(pattern, instruction, re.IGNORECASE):
        field = labels[" ".join(label.lower().split())]
        angular = field == "angle_span_deg"
        length_unit = unit.lower() in _METERS
        if angular == length_unit:
            raise ValueError("scene_layout_explicit_dimension_unit_invalid: " + field)
        try:
            expected = _number(value) * (_METERS[unit.lower()] if length_unit else 1)
        except ValueError as exc:
            raise ValueError("scene_layout_explicit_dimension_number_unsupported: " + field) from exc
        actual = getattr(spec.pattern, field)
        if actual is None or not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=1e-12):
            raise ValueError("scene_layout_explicit_dimension_mismatch: pattern." + field)


def validate_explicit_layout_constraints(instruction, spec):
    validate_explicit_spacing(instruction, spec)
    validate_explicit_pattern_dimensions(instruction, spec)
