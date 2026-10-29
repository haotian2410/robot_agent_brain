"""Semantic helpers.

Keep this package initializer lazy: contracts import the lightweight scene
reference models, while task-domain policy imports the contracts themselves.
Eager imports here would create a circular import during protocol loading.
"""

__all__ = ["validate_operation_contract", "TaskDomainPolicy", "DomainPolicyRegistry"]


def __getattr__(name):
    if name == "validate_operation_contract":
        from .operation_contracts import validate_operation_contract
        return validate_operation_contract
    if name == "TaskDomainPolicy":
        from .task_domain_policy import TaskDomainPolicy
        return TaskDomainPolicy
    if name == "DomainPolicyRegistry":
        from .domain_policy_registry import DomainPolicyRegistry
        return DomainPolicyRegistry
    raise AttributeError(name)
