"""Read-only OLS identity/metadata parity check, no dynamic upload support."""
import json
from pathlib import Path
from .protocol import digest, loopback_url


def check_ols(client, base_url, root):
    root = Path(root)
    base_url = loopback_url(base_url)
    counts = {}
    for kind, plural, filename in (("model","models","model_index.json"), ("robot","robots","robot_index.json"),
                                   ("scene","scenes","scene_index.json")):
        index = json.loads((root / plural / filename).read_text())
        expected = ({int(i):name for i,name in index["by_id"].items()} if kind != "scene"
                    else {item["id"]:item["name"] for item in index})
        response = client.get(base_url + "/list", params={"type":kind,"uid":0})
        response.raise_for_status()
        items = response.json()["items"]
        if len(items) != len(expected) or {item["id"]:item["name"] for item in items} != expected:
            raise ValueError("ols_catalog_mismatch:" + kind)
        for identifier,name in expected.items():
            remote = client.get(base_url + "/" + kind, params={"id":identifier,"uid":0})
            remote.raise_for_status()
            local = json.loads((root / plural / str(identifier) / (name + ".json")).read_text())
            payload = remote.json()
            # OLS merges the files manifest into metadata for models/robots.
            comparison = {key:payload.get(key) for key in local}
            if digest(comparison) != digest(local):
                raise ValueError(f"ols_metadata_mismatch:{kind}:{identifier}")
        counts[kind] = len(expected)
    return {"matched":True,"counts":counts}
