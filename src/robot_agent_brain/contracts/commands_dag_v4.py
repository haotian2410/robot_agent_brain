"""Stable Python import names for the 4.1 per-arm sequence contract.

4.0 shared-scheduling payloads are not accepted or silently upgraded.
"""
from .commands_sequence_v41 import (
    CommandsFileV41 as CommandsFileV4,
    SequenceCommand as DagCommand,
    canonical_commands_v41 as canonical_commands_v4,
)
