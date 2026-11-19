"""No trusted remote revision means every request rechecks all metadata."""
import json
from dataclasses import FrozenInstanceError
import httpx
import pytest
from robot_agent_brain.web.assets import check_ols


@pytest.mark.parametrize("changed_kind", ["model","robot","scene"])
def test_prior_success_never_hides_metadata_change(tmp_path, changed_kind):
    for kind,plural in (("model","models"),("robot","robots"),("scene","scenes")):
        root=tmp_path/plural
        (root/"1").mkdir(parents=True)
        (root/f"{kind}_index.json").write_text(json.dumps({"by_id":{"1":kind}}))
        (root/"1"/f"{kind}.json").write_text('{"value":1}')
    changed=False
    calls=[]
    def handler(request):
        kind=request.url.path.removeprefix("/")
        calls.append(kind)
        if kind=="list":
            return httpx.Response(200,json={"items":[{"id":1,"name":request.url.params["type"],"version":"same-stat-revision"}]})
        return httpx.Response(200,json={"value":2 if changed and kind==changed_kind else 1})
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        original=check_ols(client,"http://127.0.0.1:8000",tmp_path)
        assert original["verification"]["reusable"] is False
        assert len(calls)==6
        changed=True
        with pytest.raises(ValueError,match=f"ols_metadata_mismatch:{changed_kind}:1"):
            check_ols(client,"http://127.0.0.1:8000",tmp_path)
        assert calls.count(changed_kind)==2


def test_snapshot_is_immutable_and_has_no_remote_authority():
    from robot_agent_brain.web.ols_snapshot import VerifiedOLSSnapshot
    snapshot=VerifiedOLSSnapshot.from_verified_records({"model:1":{"name":"apple"}},"http://localhost")
    assert snapshot.remote_revision is None and not snapshot.reusable
    with pytest.raises(FrozenInstanceError):
        snapshot.reusable=True
