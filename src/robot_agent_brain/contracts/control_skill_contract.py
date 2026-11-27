"""Validated snapshot of explicitly advertised Control capabilities.

This is an adapter-facing contract, never inferred from a model reply or skill
names. Legacy controllers that do not advertise v4 remain unsupported for v4.
"""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from jsonschema import Draft202012Validator
from .strict_json import validate_json


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
        validate_json(self.parameters_schema)
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


class OperationSkillSemantics(BaseModel):
    """Trusted operation meaning, not inferred from a skill's name."""
    model_config = ConfigDict(extra="forbid")
    required_skill_sequence: list[str] = Field(min_length=1)
    # skill name -> parameter name -> path in the canonical operation.
    parameter_bindings: dict[str, dict[str, str]] = Field(default_factory=dict)


class ControlSkillContract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: str = Field(min_length=1)
    supported_protocols: list[str] = Field(min_length=1)
    expansion_level: Literal["atomic", "task"]
    skills: dict[str, RegisteredControlSkill] = Field(min_length=1)
    operation_semantics: dict[str, OperationSkillSemantics] = Field(default_factory=dict)

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
        for rule in self.operation_semantics.values():
            if not set(rule.required_skill_sequence) <= set(self.skills) or not set(rule.parameter_bindings) <= set(self.skills):
                raise ValueError("control_operation_semantics_unregistered_skill")
        return self

    def validate_operation(self, operation, steps, bindings=None):
        kind = operation.task_type.value
        rule = self.operation_semantics.get(kind)
        if rule is None:
            raise ValueError("control_operation_semantics_missing: " + kind)
        names = iter(step["skill_name"] for step in steps)
        if any(not any(actual == required for actual in names) for required in rule.required_skill_sequence):
            raise ValueError("control_operation_skill_semantics_lost: " + operation.operation_id)
        data = operation.model_dump(mode="json", exclude_none=True)
        if data.get("placement_target", {}).get("reference") is not None and bindings is not None:
            reference = data["placement_target"]["reference"]
            if reference not in bindings:
                raise ValueError("control_operation_placement_reference_unresolved")
            data["placement_target"]["reference"] = bindings[reference]
        required_paths = {name for name in ("motion_direction", "distance_m") if data.get(name) is not None}
        required_paths.update("placement_target." + name for name, value in data.get("placement_target", {}).items() if value is not None)
        covered = set()
        for skill_name, bindings in rule.parameter_bindings.items():
            for parameter, path in bindings.items():
                value = data
                for part in path.split("."):
                    if not isinstance(value, dict) or part not in value:
                        value = None
                        break
                    value = value[part]
                if value is None:
                    continue
                covered.add(path)
                if path == "placement_target":
                    covered.update("placement_target." + name for name in value)
                matching = [step for step in steps if step["skill_name"] == skill_name]
                if not matching or any(step["parameters"].get(parameter) != value for step in matching):
                    raise ValueError("control_operation_parameter_semantics_lost: " + path)
        if not required_paths <= covered:
            raise ValueError("control_operation_semantics_unexpressible: " + ",".join(sorted(required_paths - covered)))

    def validate_commands(self, commands):
        if commands.schema_version not in self.supported_protocols:
            raise ValueError("unsupported_protocol_version: dual_arm_sequence_4.1")
        if commands.skill_contract_revision != self.revision:
            raise ValueError("control_skill_contract_revision_mismatch")
        for command in commands.commands:
            validate_json(command.parameters)
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
        return commands
