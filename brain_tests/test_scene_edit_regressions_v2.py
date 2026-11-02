import json

from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.asset_library import BrainAssetView
from robot_agent_brain.contracts.task_intent import TaskEntity
from robot_agent_brain.scene.asset_resolver import AssetResolver
from robot_agent_brain.scene.user_feedback import explain_issue
from robot_agent_brain.errors import BrainIssue


class _Assets:
    typed_namespaces = True
    supports_features = True
    demo_assets = False

    def __init__(self):
        self.items = {
            "mug": BrainAssetView(library_asset_id=14, metadata_ref="$LIBRARY_SERVER/14",
                                   semantic_name="mug", category="container", dimensions_m=(.1, .1, .1),
                                   local_aabb_min_m=(-.05, -.05, 0), local_aabb_max_m=(.05, .05, .1)),
            "apple": BrainAssetView(library_asset_id=1, metadata_ref="$LIBRARY_SERVER/1",
                                     semantic_name="apple", category="fruit", dimensions_m=(.08, .08, .08),
                                     local_aabb_min_m=(-.04, -.04, -.04), local_aabb_max_m=(.04, .04, .04)),
        }

    def find_by_name(self, name):
        item = self.items.get(name)
        return [item] if item else []

    def find_by_category(self, category):
        return [item for item in self.items.values() if item.category == category]

    def resolve(self, ref, asset_type=None):
        return next(item for item in self.items.values() if item.metadata_ref == ref)


def test_webeditor_aliases_include_qwen_english_cup_forms():
    aliases = BrainConfig.load("config/webeditor.json").load_semantic_aliases()
    assert aliases["cup"] == "mug"
    assert aliases["coffee cup"] == "mug"
    assert aliases["杯子"] == "mug"


def test_scene_add_plain_color_can_use_asset_and_renderer_override():
    assets = _Assets()
    entity = TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", color="blue")
    binding = AssetResolver(assets, aliases={"cup": "mug"},
                            default_refs={"apple": "$LIBRARY_SERVER/1"}).resolve(
                                entity, allow_default=True, allow_color_override=True)
    assert binding.model.semantic_name == "apple"
    assert binding.color_override == "#0000FF"


def test_scene_add_plain_color_override_does_not_require_catalog_feature_tags():
    assets = _Assets()
    assets.supports_features = False
    entity = TaskEntity(entity_id="apple", semantic_name="apple", category="fruit", color="blue")
    binding = AssetResolver(assets, default_refs={"apple": "$LIBRARY_SERVER/1"}).resolve(
        entity, allow_default=True, allow_color_override=True)
    assert binding.color_override == "#0000FF"


def test_position_feedback_uses_actual_relation_not_hardcoded_right():
    issue = BrainIssue(code="scene_edit_position_ambiguous", stage="scene_edit",
                       message="scene_edit_position_ambiguous",
                       details={"relation": "left_of"})
    explain_issue(issue, ValueError(issue.message), None, _Assets())
    assert "左侧" in issue.clarification_question
    assert "右边" not in issue.clarification_question


def test_position_feedback_keeps_right_relation_when_requested():
    issue = BrainIssue(code="scene_edit_position_ambiguous", stage="scene_edit",
                       message="scene_edit_position_ambiguous",
                       details={"relation": "right_of"})
    explain_issue(issue, ValueError(issue.message), None, _Assets())
    assert "右侧" in issue.clarification_question
    assert "左侧" not in issue.clarification_question
