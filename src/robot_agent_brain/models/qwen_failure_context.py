"""Small explicit adapter for the failure-context.v1 provider boundary."""
from .failure_context import FailureContextDecision, FailureContextRequest


class QwenFailureContext:
    """Expose only the read-only recovery operation, never command execution."""

    def __init__(self, provider):
        if not hasattr(provider, "recover_failure"):
            raise TypeError("provider_failure_context_unsupported")
        self.provider = provider

    def recover(self, request: FailureContextRequest) -> FailureContextDecision:
        return self.provider.recover_failure(request)
