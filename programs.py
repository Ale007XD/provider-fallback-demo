"""
FSM program: credit application with provider fallback.

Flow:
  s1_collect → try_s2 [TOOL, output_key=provider_ok] 
             → check_s2_result [CONDITION: $provider_ok < 1]
                 then  → switch_provider → s2_after_switch → s3_setup
                 otherwise → s3_setup
             → s3_decision → approved [terminal]

Key insight: attempt_llm_step returns 0 (fail) or 1 (success) as output_key=provider_ok.
ASTEngine supports $var > N comparison — used for branch decision.
"""
from __future__ import annotations

from nano_vm.models import Program, Step, StepType


def build_program(failure_mode: str) -> Program:
    """
    Build the credit application program.
    Provider-agnostic DSL — same program for both failure scenarios.
    failure_mode passed as runtime context, not baked into program.
    """
    return Program(
        name="credit_application_provider_fallback",
        description="Credit application with automatic provider fallback on failure.",
        steps=[
            # --- Step 1: collect application ---
            Step(
                id="set_step_s1",
                type=StepType.TOOL,
                tool="set_current_step",
                args={"step_id": "s1_collect"},
            ),
            Step(
                id="s1_collect",
                type=StepType.LLM,
                prompt="You are collecting a credit application. "
                       "Summarize: applicant data, income, debt ratio.",
                output_key="application_data",
            ),
            # --- Step 2: verify income (may fail → switch provider) ---
            Step(
                id="set_step_s2",
                type=StepType.TOOL,
                tool="set_current_step",
                args={"step_id": "s2_verify"},
            ),
            Step(
                id="try_s2",
                type=StepType.TOOL,
                tool="attempt_llm_step",
                args={"step_id": "s2_verify"},
                output_key="provider_ok",   # 1 = success, 0 = failed
            ),
            Step(
                id="check_s2_result",
                type=StepType.CONDITION,
                condition="$provider_ok < 1",   # True when provider failed
                then="switch_provider",
                otherwise="s3_setup",
            ),
            Step(
                id="switch_provider",
                type=StepType.TOOL,
                tool="do_switch_provider",
                args={},
            ),
            Step(
                id="s2_after_switch",
                type=StepType.TOOL,
                tool="attempt_llm_step",
                args={"step_id": "s2_verify"},
                output_key="verify_result",
            ),
            # --- Step 3: policy decision ---
            Step(
                id="s3_setup",
                type=StepType.TOOL,
                tool="set_current_step",
                args={"step_id": "s3_decision"},
            ),
            Step(
                id="s3_decision",
                type=StepType.LLM,
                prompt="Check policy: income >= 5000 AND debt_ratio < 40%. "
                       "State APPROVED or DENIED with reason.",
                output_key="decision",
            ),
            # --- Terminal ---
            Step(
                id="approved",
                type=StepType.LLM,
                prompt="Confirm: application processing complete.",
                output_key="final_confirmation",
                is_terminal=True,
            ),
        ],
    )
