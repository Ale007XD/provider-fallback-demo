"""
Mock LLM providers for provider-fallback demo.

Each provider returns a deterministic response for the step.
Failure injection is controlled externally via FailureConfig.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from nano_vm.adapters.base import LLMAdapter


class ProviderUnavailableError(Exception):
    """Raised when the current provider is unavailable."""


@dataclass
class FailureConfig:
    """Controls how failures are injected into the primary provider."""

    mode: str  # "retry" | "hard"
    fail_on_step: str = "s2_verify"
    max_retries: int = 3  # used in retry mode

    # internal counters
    _attempt: int = field(default=0, init=False, repr=False)

    def should_fail(self, step_id: str, provider: str) -> bool:
        if step_id != self.fail_on_step:
            return False
        if provider != "claude":
            return False  # fallback provider never fails
        if self.mode == "hard":
            return True
        # retry mode: fail until max_retries exhausted
        self._attempt += 1
        return self._attempt <= self.max_retries

    def reset(self) -> None:
        self._attempt = 0


class MockAdapter(LLMAdapter):
    """
    Single adapter that routes to 'current_provider' stored in shared state.
    Failure injection happens here — FSM sees it as a tool error, not an LLM error.
    This adapter is stateless; provider routing is done via state.data.
    """

    # Canned responses per (provider, step_id)
    _RESPONSES: dict[tuple[str, str], str] = {
        ("claude", "s1_collect"): "Application collected. Applicant: John Doe, income=6200, debt_ratio=32%.",
        ("gpt",   "s1_collect"): "Application collected. Applicant: John Doe, income=6100, debt_ratio=31%.",
        ("qwen",  "s1_collect"): "Application collected. Applicant: John Doe, income=6300, debt_ratio=33%.",
        ("claude", "s2_verify"): "Income verified: 6200. Debt ratio: 32%. Both within policy.",
        ("gpt",   "s2_verify"): "Income verified: 6100. Debt ratio: 31%. Both within policy.",
        ("qwen",  "s2_verify"): "Income verified: 6300. Debt ratio: 33%. Both within policy.",
        ("claude", "s3_decision"): "Policy check passed. Recommendation: APPROVED.",
        ("gpt",   "s3_decision"): "Policy check passed. Recommendation: APPROVED.",
        ("qwen",  "s3_decision"): "Policy check passed. Recommendation: APPROVED.",
    }

    def __init__(self, failure_config: FailureConfig, state_ref: dict[str, Any]) -> None:
        self._failure_config = failure_config
        self._state_ref = state_ref  # shared mutable dict: {"provider": "claude"}

    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        step_id = self._state_ref.get("current_step_id", "unknown")
        provider = self._state_ref.get("current_provider", "claude")

        if self._failure_config.should_fail(step_id, provider):
            raise ProviderUnavailableError(f"{provider} unavailable on step {step_id}")

        response = self._RESPONSES.get((provider, step_id))
        if response is None:
            response = f"[{provider}] Completed step {step_id}."
        return response
