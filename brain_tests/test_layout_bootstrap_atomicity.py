import pytest

from robot_agent_brain.application import BrainApplication
from robot_agent_brain.config import BrainConfig
from robot_agent_brain.contracts.turn import BrainTurn
from robot_agent_brain.adapters.local_scene_platform import LocalScenePlatform
from test_application_artifacts import Provider
from test_layout_transaction import setup


class CountingPlatform(LocalScenePlatform):
    def __init__(self):
        super().__init__()
        self.loads = 0
        self.patches = 0

    def load_scene(self, scene, **kwargs):
        self.loads += 1
        return super().load_scene(scene, **kwargs)

    def apply_patch(self, patch):
        self.patches += 1
        return super().apply_patch(patch)


@pytest.mark.parametrize("spacing,success", [(.12, True), (2, False)])
@pytest.mark.parametrize("file_backed", [False, True])
def test_application_bootstrap_layout_publishes_only_complete_scene(tmp_path, spacing, success, file_backed):
    scene, spec, _ = setup(spacing)
    if file_backed:
        from robot_agent_brain.contracts.scene import parse_scene_document
        document = scene.model_dump(mode="json")
        document.update(scene_id=123, scene_version=17, scene_sub_version=2)
        document["scene_name_Chinese"] = "空场景"
        scene = parse_scene_document(document, uint32=False).view
    template_before = scene.raw_document()
    turn = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="两行三列苹果", arrangement_spec=spec)
    provider = Provider(turn)
    platform = CountingPlatform()
    app = BrainApplication(BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path),
                                     scene_platform_object_ids={0}),
                           provider=provider, platform_factory=lambda: platform)
    app.bootstrapper.template_scene = scene
    report = app.handle(turn.instruction, session_id="layout-bootstrap")
    session = app.get_session("layout-bootstrap")
    assert provider.count == 1
    assert scene.raw_document() == template_before
    assert platform.patches == 0
    if success:
        assert report.run_status == "success", report.error
        assert platform.loads == 1
        assert session.scene.scene_version == 1
        assert len(session.scene.objects) == 7
        if file_backed:
            assert session.scene.raw_document()["scene_name_Chinese"] == "空场景"
        record = session.arrangement_index.get(spec.arrangement_id)
        assert record.scene_version == 1
        assert report.request_id in session.layout_request_receipts
        canonical = turn.model_copy(update={"asset_catalog_revision": app.pipeline.asset_catalog.revision})
        replay = session.process_turn(report.request_id, canonical)
        assert replay.scene_replacement.scene_version == 1
        assert platform.loads == 1
    else:
        assert report.run_status == "failed", report
        assert platform.loads == 0
        assert session.scene is None
        assert not session.arrangement_index.snapshot()
        assert not session.layout_request_receipts


def test_failed_empty_bootstrap_reservation_survives_application_restart(tmp_path):
    scene, spec, _ = setup(2)
    bad = BrainTurn(status="accepted", turn_kind="scene_layout", instruction="两行三列苹果",
                    arrangement_spec=spec)
    config = BrainConfig(provider="replay", planner="recipe", output_dir=str(tmp_path),
                         scene_platform_object_ids={0})
    first = BrainApplication(config, provider=Provider(bad), platform_factory=CountingPlatform)
    first.bootstrapper.template_scene = scene
    failed = first.handle(bad.instruction, session_id="restart-empty")
    assert failed.run_status == "failed"
    end = first.get_session("restart-empty").next_scene_object_id
    assert end == 7
    data = spec.model_dump()
    data["spacing"]["value_m"] = .12
    good = bad.model_copy(update={"arrangement_spec": type(spec).model_validate(data)})
    second = BrainApplication(config, provider=Provider(good), platform_factory=CountingPlatform)
    second.bootstrapper.template_scene = scene
    restored = second.get_session("restart-empty")
    assert restored.scene is None and restored.next_scene_object_id == end
    assert restored.seen_scene_object_ids == set(range(1, end))
    report = second.handle(good.instruction, session_id="restart-empty")
    assert report.run_status == "success", report.error
    members = restored.arrangement_index.get(spec.arrangement_id).slot_bindings.values()
    assert min(members) >= end
    assert restored.scene.scene_version == 1
