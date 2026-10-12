"""Explicit metadata tags, not inferred display-name or pixel colors."""
import re

ALIASES = {"红色": "red", "蓝色": "blue", "白色": "white", "黄色": "yellow",
           "黑色": "black", "绿色": "green", "粉色": "pink", "灰色": "gray",
           "棕色": "brown", "木制": "wooden", "编织": "woven", "双层": "double"}


def requested_features(entity):
    return [ALIASES.get(value.strip().casefold(), value.strip().casefold())
            for value in ([entity.color] if entity.color else []) + entity.tags]


def matches_features(asset, entity):
    available = {word for tag in asset.tags for word in re.split(r"[\s,]+", tag.casefold()) if word}
    return all(value in available or value in asset.tags for value in requested_features(entity))
