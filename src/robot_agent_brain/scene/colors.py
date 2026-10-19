"""Declared instance colors and metadata evidence; never pixel inference."""
import re

COLOR_POLICY_VERSION = "1"
PALETTE = {"red": "#FF0000", "blue": "#0000FF", "green": "#00FF00",
           "yellow": "#FFFF00", "black": "#000000", "white": "#FFFFFF",
           "gray": "#808080", "orange": "#FFA500", "pink": "#FFC0CB",
           "purple": "#800080", "brown": "#A52A2A", "golden": "#FFD700"}
ALIASES = dict(zip("红 蓝 绿 黄 黑 白 灰 橙 粉 紫 棕 金".split(), PALETTE))
ALIASES.update({key + "色": value for key, value in list(ALIASES.items())})
ALIASES.update({"grey": "gray", "gold": "golden"})


def color_name(value):
    value = value.strip().casefold()
    return ALIASES.get(value, value)


def color_tags(tags):
    return tuple(sorted({color_name(word) for tag in tags for word in re.split(r"[\s,]+", tag)
                         if color_name(word) in PALETTE}))


class ColorResolver:
    @staticmethod
    def resolve(value):
        if not isinstance(value, str) or not value.strip():
            raise ValueError("scene_edit_color_unknown: 请提供颜色名称或 HEX")
        value = value.strip()
        if re.fullmatch(r"#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?", value):
            return value.upper()
        name = color_name(value)
        if name not in PALETTE:
            raise ValueError("scene_edit_color_unknown: 请提供明确颜色或 HEX: " + value)
        return PALETTE[name]


class ColorEvidenceResolver:
    def __init__(self, assets=None):
        self.assets = assets

    def matches(self, value, obj, index):
        requested = ColorResolver.resolve(value)
        renderer = index.component(obj.object_id_in_scene, "MeshRenderer")
        if renderer is not None and renderer.properties.get("forceOverrideColor") is not None:
            actual = ColorResolver.resolve(renderer.properties["forceOverrideColor"])
            return actual == requested if len(value.strip()) == 9 and value.strip().startswith("#") else actual[:7] == requested[:7]
        reference = index.metadata_ref(obj.object_id_in_scene)
        if self.assets is None or reference is None:
            raise ValueError("grounding_evidence_missing: color")
        kind = index.metadata_type(obj.object_id_in_scene)
        asset = self.assets.resolve(reference, kind) if kind else self.assets.resolve(reference)
        colors = asset.color_tags or color_tags(asset.tags)
        if not colors or value.strip().startswith("#"):
            raise ValueError("grounding_evidence_missing: color")
        return color_name(value) in colors
