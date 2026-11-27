"""Validated snapshot of explicitly advertised Control capabilities.

This is an adapter-facing contract, never inferred from a model reply or skill
names. Legacy controllers that do not advertise v4 remain unsupported for v4.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from jsonschema import Draft202012Validator


class RegisteredHoldingEffect(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["preserve", "acquire", "release"]
    object_parameter: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def parameter_for_acquisition(self):
        if (self.action == "acquire") != (self.object_parameter is not None):
            raise ValueError("control_skill_holding_effect_invalid")
        return self


class RegisteredControlSkill(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expansion_level: Literal["atomic", "task"]
    parameters_schema: dict
    # None means the controller has not advertised object-parameter semantics;
    # {} explicitly declares an object-free skill (e.g. lift/home).
    object_parameters: dict[str, Literal["source_object_id", "destination_object_id", "reference_object_id"]] | None = None
    holding_effect: RegisteredHoldingEffect | None = None

    @model_validator(mode="after")
    def valid_schema(self):
        if self.holding_effect is not None and self.holding_effect.action == "acquire":
            if self.holding_effect.object_parameter not in (self.object_parameters or {}):
                raise ValueError("control_skill_holding_effect_binding_missing")
        Draft202012Validator.check_schema(self.parameters_schema)
        # Validation must be offline. Never retrieve references supplied by a
        # remote capability endpoint while validating an execution request.
        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"$ref", "$dynamicRef"} and not item.startswith("#"):
                        raise ValueError("control_skill_schema_external_reference")
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(self.parameters_schema)
        return self


class ControlSkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1)
    supported_protocols: list[str] = Field(min_length=1)
    expansion_level: Literal["atomic", "task"]
    skills: dict[str, RegisteredControlSkill] = Field(min_length=1)
    supports_sync: bool = Field(default=False, strict=True)
    supports_resources: bool = Field(default=False, strict=True)
    supports_hold: bool = Field(default=False, strict=True)

    @model_validator(mode="after")
    def coherent_advertisement(self):
        if (any(not version.strip() or version != version.strip() for version in self.supported_protocols)
                or len(set(self.supported_protocols)) != len(self.supported_protocols)):
            raise ValueError("control_skill_protocol_list_invalid")
        for name, skill in self.skills.items():
            if not name.strip() or name != name.strip():
                raise ValueError("control_skill_name_invalid")
            if skill.expansion_level != self.expansion_level:
                raise ValueError("control_skill_expansion_level_mismatch: " + name)
        return self

    def validate_commands(self, commands):
        if commands.schema_version not in self.supported_protocols:
            raise ValueError("unsupported_protocol_version: commands_dag_v4")
        if commands.skill_contract_revision != self.revision:
            raise ValueError("control_skill_contract_revision_mismatch")
        for command in commands.commands:
            skill = self.skills.get(command.skill_name)
            if skill is None:
                raise ValueError("control_skill_unregistered: " + command.skill_name)
            if skill.expansion_level != self.expansion_level:
                raise ValueError("control_skill_expansion_level_mismatch: " + command.skill_name)
            errors = sorted(Draft202012Validator(skill.parameters_schema).iter_errors(command.parameters),
                            key=lambda error: str(list(error.path)))
            if errors:
                path = ".".join(map(str, errors[0].path)) or "parameters"
                raise ValueError(f"control_skill_parameters_invalid: {command.command_id}.{path}")
        for field, enabled in (("sync_groups", self.supports_sync),
                               ("resource_groups", self.supports_resources),
                               ("hold_constraints", self.supports_hold)):
            if getattr(commands, field) and not enabled:
                raise ValueError("control_dag_feature_unsupported: " + field)
        return commands
