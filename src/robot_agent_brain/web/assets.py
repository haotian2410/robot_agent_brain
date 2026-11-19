"""Read-only OLS identity/metadata parity check, no dynamic upload support."""
import json
from pathlib import Path
from ..perf_trace import timed, span
from ..adapters.ols_index import hidden_ids, index_by_id
from .protocol import digest, loopback_url
from .ols_snapshot import VerifiedOLSSnapshot


@timed("ols.check_catalog", component="brain.web.assets")
def check_ols(client, base_url, root):
    root = Path(root)
    base_url = loopback_url(base_url)
    counts = {}
    verified_records = {}
    for kind, plural, filename in (("model","models","model_index.json"), ("robot","robots","robot_index.json"),
                                   ("scene","scenes","scene_index.json")):
        index = json.loads((root / plural / filename).read_text(encoding="utf-8"))
        expected = index_by_id(index)
        verified_records[kind + ":index"] = index
        # /list hides no_display assets; direct ID lookup still exposes them.
        hidden = hidden_ids(index)
        listed = {identifier: name for identifier, name in expected.items() if identifier not in hidden}
        with span("ols.check_list", component="ols", source="web/assets.py:check_ols", kind=kind, requests=1, wait_kind="http"):
            response = client.get(base_url + "/list", params={"type":kind,"uid":0})
        response.raise_for_status()
        items = response.json()["items"]
        if len(items) != len(listed) or {item["id"]:item["name"] for item in items} != listed:
            raise ValueError("ols_catalog_mismatch:" + kind)
        for identifier,name in expected.items():
            with span("ols.check_item", component="ols", source="web/assets.py:check_ols", kind=kind, requests=1, wait_kind="http"):
                remote = client.get(base_url + "/" + kind, params={"id":identifier,"uid":0})
            remote.raise_for_status()
            local = json.loads((root / plural / str(identifier) / (name + ".json")).read_text(encoding="utf-8"))
            payload = remote.json()
            # OLS merges the files manifest into metadata for models/robots.
            comparison = {key:payload.get(key) for key in local}
            if digest(comparison) != digest(local):
                raise ValueError(f"ols_metadata_mismatch:{kind}:{identifier}")
            verified_records[f"{kind}:{identifier}"] = local
        counts[kind] = len(expected)
    snapshot = VerifiedOLSSnapshot.from_verified_records(verified_records, base_url)
    # Diagnostics only: no snapshot lookup and no early-return/cache hit path.
    with span("ols.verification_snapshot", component="brain.web.assets",
              source="strict_full_metadata", status="verified_not_reusable"):
        pass
    return {"matched":True,"counts":counts,
            "verification": {"policy": snapshot.policy, "reusable": snapshot.reusable,
                "scope": snapshot.scope, "local_metadata_digest": snapshot.local_metadata_digest,
                "remote_revision": snapshot.remote_revision, "verified_at": snapshot.verified_at}}
