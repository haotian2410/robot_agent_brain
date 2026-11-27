"""Model-owned skill chains; scheduling remains exclusively Python-owned."""
from pydantic import BaseModel, ConfigDict, Field, model_validator, field_validator
from .strict_json import validate_json


class AtomicSkillDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_name: str = Field(min_length=1)
    parameters: dict = Field(default_factory=dict)

    @field_validator("parameters", mode="before")
    @classmethod
    def standard_json_object(cls, value):
        if type(value) is not dict:
            raise ValueError("control_skill_parameters_object_required")
        return validate_json(value)


class OperationSkillDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation_id: str = Field(min_length=1)
    steps: list[AtomicSkillDraft] = Field(min_length=1)


class DualSkillDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operations: list[OperationSkillDraft] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_operations(self):
        ids = [op.operation_id for op in self.operations]
        if len(ids) != len(set(ids)):
            raise ValueError("commands_v4_duplicate_operation")
        return self

    def steps_for(self, operation_ids):
        expected = list(operation_ids)
        found = {op.operation_id: op.steps for op in self.operations}
        if len(expected) != len(set(expected)) or set(expected) != set(found):
            raise ValueError("commands_v4_operation_coverage_invalid")
        return {key: [step.model_dump() for step in found[key]] for key in expected}
