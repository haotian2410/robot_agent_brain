"""Validate original JSON values before serialization can coerce them."""
import math


def validate_json(value):
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    if type(value) is list:
        for item in value:
            validate_json(item)
        return value
    if type(value) is dict and all(type(key) is str for key in value):
        for item in value.values():
            validate_json(item)
        return value
    raise ValueError("non_json_or_nonfinite_value")
