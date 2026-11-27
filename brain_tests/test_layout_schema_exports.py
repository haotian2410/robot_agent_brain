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


def test_resource_groups_are_not_untyped_arrays():
    schema = schema_documents()["commands_dag_v4.schema.json"]
    assert schema["properties"]["resource_groups"]["items"] == {"$ref": "#/$defs/ResourceGroup"}
    assert schema["$defs"]["ResourceGroup"]["additionalProperties"] is False
