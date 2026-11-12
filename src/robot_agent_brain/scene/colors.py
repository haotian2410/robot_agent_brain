"""Declared instance colors and metadata evidence; never pixel inference."""
import re

COLOR_POLICY_VERSION = "3"
PALETTE = {"red": "#FF0000", "blue": "#0000FF", "green": "#00FF00",
           "yellow": "#FFFF00", "black": "#000000", "white": "#FFFFFF",
           "gray": "#808080", "orange": "#FFA500", "pink": "#FFC0CB",
           "purple": "#800080", "brown": "#A52A2A", "golden": "#FFD700"}
ALIASES = dict(zip("红 蓝 绿 黄 黑 白 灰 橙 粉 紫 棕 金".split(), PALETTE))
ALIASES.update({key + "色": value for key, value in list(ALIASES.items())})
ALIASES.update({"grey": "gray", "gold": "golden"})
HEX_TO_NAME = {value: name for name, value in PALETTE.items()}


def color_name(value):
    value = value.strip().casefold()
    return ALIASES.get(value, value)


def color_name_of(value):
    """Name of an exact palette HEX, or None.  A near colour is never guessed."""
    if not isinstance(value, str):
        return None
    return HEX_TO_NAME.get(value.strip().upper()[:7])


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


def instance_color_evidence(index, obj, assets):
    """Declared colours of one instance as ``(hex values, exact)``, or None when nothing declares any.

    An override is pixel-exact; an asset tag only names a colour family, so it answers
    「红色」 but never a literal ``#RRGGBB`` -- that difference is what ``exact`` carries.
    """
    renderer = index.component(obj.object_id_in_scene, "MeshRenderer")
    override = renderer.properties.get("forceOverrideColor") if renderer is not None else None
    if override is not None:
        return (ColorResolver.resolve(override),), True
    reference = index.metadata_ref(obj.object_id_in_scene)
    if assets is None or reference is None:
        return None
    kind = index.metadata_type(obj.object_id_in_scene)
    try:
        asset = assets.resolve(reference, kind) if kind else assets.resolve(reference)
    except (ValueError, AttributeError):
        return None
    names = asset.color_tags or color_tags(asset.tags)
    colors = tuple(PALETTE[name] for name in names if name in PALETTE)
    return (colors, False) if colors else None


class ColorEvidenceResolver:
    def __init__(self, assets=None):
        self.assets = assets

    def matches(self, value, obj, index):
        """True/False against declared evidence, None when this instance declares no colour.

        ``None`` is neither a match nor a mismatch: it lets a caller keep the
        instances that did declare a colour instead of letting one silent
        sibling abort the whole selection.
        """
        try:
            requested = ColorResolver.resolve(value)
            evidence = instance_color_evidence(index, obj, self.assets)
        except ValueError:
            # An unreadable colour -- in the request or in the stored paint -- declares
            # nothing.  Colour is a soft preference, never a reason to abort a turn.
            return None
        if evidence is None:
            return None
        declared, exact = evidence
        if value.strip().startswith("#") and not exact:
            return None
        def same(actual):
            return actual == requested if len(value.strip()) == 9 else actual[:7] == requested[:7]
        return any(same(item) for item in declared)
