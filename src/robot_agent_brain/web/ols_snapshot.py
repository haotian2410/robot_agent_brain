"""Evidence of a completed parity check, NOT a reusable cache authorization.

The current OLS version is based on size/mtime. Until it supplies an atomic,
content-covering revision, every production task must verify full metadata.
This snapshot does not attest mesh bytes or concurrent catalog consistency.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json


@dataclass(frozen=True)
class VerifiedOLSSnapshot:
    local_metadata_digest: str
    verified_at: str
    source: str
    remote_revision: str | None = None
    policy: str = "strict_full_metadata"
    reusable: bool = False
    scope: str = "sequential_metadata_parity_only"

    @classmethod
    def from_verified_records(cls, records, source):
        encoded = json.dumps(records, sort_keys=True, ensure_ascii=False,
                             separators=(",", ":")).encode()
        return cls(hashlib.sha256(encoded).hexdigest(),
                   datetime.now(timezone.utc).isoformat(), source)
