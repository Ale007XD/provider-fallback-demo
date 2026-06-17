# provider-fallback-demo

Demonstrates the **State > Model** thesis on the real [llm-nano-vm](https://github.com/Ale007XD/nano_vm) stack.

> "What happens if your model becomes unavailable mid-task?"

In June 2026, access to two Anthropic models (Claude Fable 5 and Claude Mythos 5) was suspended worldwide in response to a government export control directive — with no advance warning to the companies depending on them. Closed-model access can be revoked at any time, for reasons that have nothing to do with the model's technical performance. This demo treats that as an architectural problem, not a hypothetical one.

---

## What the demo shows

A credit application pipeline runs through a three-step FSM.
At the `verify_income` step, the primary provider (Claude) becomes unavailable.
The FSM switches to a backup provider (GPT) and completes the task.

Two failure scenarios:

| Scenario | Behavior |
|---|---|
| `--failure-mode retry` | Provider degrades: 3 attempts → `RetryLimitExceeded` → switch |
| `--failure-mode hard` | Provider disappears: 1 attempt → `ProviderUnavailable` → switch |

Both scenarios finish the same way:

```
final_status: SUCCESS
provider_final: gpt
```

---

## Architectural thesis

```
Traditional Agent:         nano-vm:

Task                       Task
  ↓                          ↓
Claude                      FSM
  ↓                          ↓
FAIL               Claude → ✗ → GPT → ✓
                             ↓
                          COMPLETE
```

The system does not bet on a provider. It bets on preserving state.

The FSM determines the path. The LLM produces a signal inside a step. The provider is an implementation detail.

---

## Output of `--both`

```
=== Scenario: RETRY ===

S1  collect_application   ✓  claude

S2  verify_income
  CLAUDE failed (1/3)
  CLAUDE failed (2/3)
  CLAUDE failed (3/3)

  EVENT: RetryLimitExceeded
  ACTION: switch_provider  claude → gpt

S3  policy_decision       ✓  GPT
    final_confirmation    ✓  GPT

RECEIPT:
{
  "final_status": "SUCCESS",
  "provider_final": "gpt",
  "switch_event": "RetryLimitExceeded",
  "trace_hash": "c6f5c32c..."
}

=== Scenario: HARD ===

S1  collect_application   ✓  claude

S2  verify_income
  EVENT: ProviderUnavailable (CLAUDE)
  ACTION: switch_provider  claude → gpt

S3  policy_decision       ✓  GPT
    final_confirmation    ✓  GPT

RECEIPT:
{
  "final_status": "SUCCESS",
  "provider_final": "gpt",
  "switch_event": "ProviderUnavailable",
  "trace_hash": "c6f5c32c..."
}

=== COMPARISON TABLE ===

  Metric                      Retry               Hard Cutoff
  ----------------------------------------------------------------
  final_status                SUCCESS             SUCCESS
  completed_steps             6                   6
  rejected_transitions        0                   0
  switch_event                RetryLimitExceeded  ProviderUnavailable
  provider_final              gpt                 gpt
  trace_hash                  c6f5c32ce3d9...     c6f5c32ce3d9...

  Different execution trace.  Same business outcome.

  State survives. Providers don't.
```

---

## Why `trace_hash` is identical

Both scenarios traverse the identical FSM path: `set_step_s1 → s1_collect → set_step_s2 → try_s2 → check_s2_result → switch_provider → s2_after_switch → s3_setup → s3_decision → approved`.

The retry logic is encapsulated inside the `try_s2` TOOL step — the FSM never sees individual attempts, only the step's final result.

`trace_hash = SHA-256(Merkle(step_results))`. When the FSM path matches, the hashes match. This is a property of the construction, not a coincidence: **same path → same state → same receipt**.

---

## Implementation

### Pattern: interceptable failure via TOOL

An LLM step in nano-vm that fails marks the step `FAILED` and stops the trace.
For the FSM to branch on a provider failure, the failure is intercepted inside a TOOL:

```
TOOL attempt_llm_step   → returns 1 (success) or 0 (failed)
CONDITION $provider_ok < 1  → then: switch_provider
                              otherwise: s3_setup
TOOL do_switch_provider → updates current_provider
TOOL attempt_llm_step   → retries on the new provider
```

The FSM only ever sees successful transitions. Provider failure is a governed event, not an exception.

### Files

```
provider_demo/
├── receipt_demo.py   # CLI: --failure-mode retry|hard|--both
├── programs.py       # FSM program (provider-agnostic DSL)
├── providers.py      # MockAdapter + FailureConfig (failure injection)
└── tools.py          # attempt_llm_step, do_switch_provider, set_current_step
```

### Known limits

- `ExecutionVM.run()` is async — every tool that calls the LLM adapter must be `async def`
- ASTEngine conditions do not support string literals as the right-hand side of a comparison (parses, always evaluates `False`); the working pattern is a numeric sentinel via `output_key`, checked as `$var < 1` / `$var > 0`
- Fallback chain is a fixed list (`claude → gpt → qwen`), not a scored or ranked choice
- `MockAdapter` does not call a real provider API — responses are deterministic by design so the demo runs without API keys

---

## What's next

- **Stage 2**: Streamlit visualization — FSM graph + live trace + Receipt panel
- **`outcome_hash`**: a hash over `(program_name, final_status, key_outputs)` only — invariant with respect to provider
- **Execution Equivalence**: `Trace_A ≠ Trace_B`, but `Outcome(A) = Outcome(B)` → a formal equivalence relation

---

## Related projects

- [llm-nano-vm](https://pypi.org/project/llm-nano-vm/) — FSM execution kernel
- [nano-vm-mcp](https://github.com/Ale007XD/nano-vm-mcp) — MCP gateway with governance
- [kyc-demo-streamlit](https://github.com/Ale007XD/kyc-demo-streamlit) — governance layer over a KYC pipeline
- 
