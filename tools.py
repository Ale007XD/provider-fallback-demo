"""
Tool implementations for provider-fallback demo.

Key pattern: attempt_llm_step() is a TOOL that calls the LLM adapter directly.
It catches ProviderUnavailableError and returns 'PROVIDER_FAILED' sentinel.
FSM sees a successful TOOL step → CONDITION can branch to switch_provider.

This is the correct nano-vm pattern for interceptable failures:
  TOOL (attempt) → CONDITION (check result) → TOOL (switch) → TOOL (retry)
"""
from __future__ import annotations

from typing import Any

from providers import MockAdapter, ProviderUnavailableError

# Shared mutable state between tools and adapter
# In a real system this would be StateContext.data
_shared: dict[str, Any] = {
    "current_provider": "claude",
    "current_step_id": "unknown",
    "provider_switched": False,
    "retry_log": [],          # list of (step_id, provider, attempt, result)
    "switch_event": None,     # "ProviderUnavailable" | "RetryLimitExceeded"
}

_adapter: MockAdapter | None = None
_STEP_PROMPTS: dict[str, str] = {
    "s1_collect": "You are collecting a credit application. Summarize: applicant data, income, debt ratio.",
    "s2_verify": "Verify income >= 5000 AND debt_ratio < 40%. Report the numbers.",
    "s3_decision": "Check policy: income >= 5000 AND debt_ratio < 40%. State APPROVED or DENIED.",
}


async def _call_adapter(prompt: str) -> str:
    """Call async adapter.complete()."""
    assert _adapter is not None
    messages = [{"role": "user", "content": prompt}]
    result = await _adapter.complete(messages)
    return result if isinstance(result, str) else result[0]


def init_tools(adapter: MockAdapter) -> None:
    global _adapter
    _adapter = adapter
    _shared["current_provider"] = "claude"
    _shared["current_step_id"] = "unknown"
    _shared["provider_switched"] = False
    _shared["retry_log"] = []
    _shared["switch_event"] = None


def set_current_step(**kwargs: Any) -> str:
    step_id = kwargs["step_id"]
    _shared["current_step_id"] = step_id
    return f"step_set:{step_id}"


async def attempt_llm_step(**kwargs: Any) -> str:
    """
    Attempt to run an LLM step via the current provider.
    Returns 'PROVIDER_FAILED' on ProviderUnavailableError so FSM can branch.
    In retry mode, retries up to max_retries before returning PROVIDER_FAILED.
    """
    assert _adapter is not None
    step_id = kwargs["step_id"]
    _shared["current_step_id"] = step_id
    prompt = _STEP_PROMPTS.get(step_id, f"Execute step {step_id}.")

    failure_config = _adapter._failure_config
    mode = failure_config.mode

    if mode == "retry":
        # Retry loop: attempt up to max_retries times, then give up
        for attempt in range(1, failure_config.max_retries + 1):
            try:
                result = await _call_adapter(prompt)
                _shared["retry_log"].append((step_id, _shared["current_provider"], attempt, "OK"))
                _shared[f"{step_id}_output"] = result
                return 1  # success sentinel
            except ProviderUnavailableError:
                _shared["retry_log"].append(
                    (step_id, _shared["current_provider"], attempt, "FAIL")
                )
        # All retries exhausted → signal switch needed
        _shared["switch_event"] = "RetryLimitExceeded"
        return 0  # failure sentinel → CONDITION branches to switch_provider
    else:
        # hard mode — single attempt
        try:
            result = await _call_adapter(prompt)
            _shared[f"{step_id}_output"] = result
            return 1  # success
        except ProviderUnavailableError:
            _shared["switch_event"] = "ProviderUnavailable"
            _shared["retry_log"].append((step_id, _shared["current_provider"], 1, "FAIL"))
            return 0  # failure


def do_switch_provider(**kwargs: Any) -> str:
    old = _shared["current_provider"]
    # Simple fallback chain: claude → gpt → qwen
    chain = ["claude", "gpt", "qwen"]
    idx = chain.index(old) if old in chain else 0
    new_provider = chain[min(idx + 1, len(chain) - 1)]
    _shared["current_provider"] = new_provider
    _shared["provider_switched"] = True
    return f"switched:{old}→{new_provider}"


def get_shared() -> dict[str, Any]:
    return _shared


TOOL_REGISTRY: dict[str, Any] = {
    "set_current_step": set_current_step,
    "attempt_llm_step": attempt_llm_step,
    "do_switch_provider": do_switch_provider,
}
