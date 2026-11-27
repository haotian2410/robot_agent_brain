import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from scripts.generate_layout_schemas import schema_documents


@pytest.mark.parametrize("name,document", list(schema_documents().items()))
def test_export_matches_canonical_contract(name, document):
    path = Path(__file__).resolve().parents[1] / "schemas" / name
    assert json.loads(path.read_text(encoding="utf-8")) == document
    Draft202012Validator.check_schema(document)


def test_public_sequence_schema_has_no_shared_scheduling_metadata():
    schema = schema_documents()["commands_dag_v4.schema.json"]
    assert schema["properties"]["schema_version"]["const"] == "4.1"
    assert not {"resource_groups", "hold_constraints", "sync_groups", "execution_policy"} & schema["properties"].keys()
    assert schema["additionalProperties"] is False
