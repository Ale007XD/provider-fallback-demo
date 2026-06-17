# provider-fallback-demo

Демонстрация тезиса **State > Model** на реальном стеке [llm-nano-vm](https://github.com/Ale007XD/nano_vm).

> "What happens if your model disappears tomorrow?"

После [истории с Fable](https://techcrunch.com/2025/06/13/fable-shuts-down-after-anthropic-restricts-access-to-its-ai-model/) это не абстракция.

---

## Что показывает демо

Кредитная заявка проходит через FSM-пайплайн из трёх шагов.
На шаге `verify_income` основной провайдер (Claude) падает.
FSM переключается на резервный (GPT) и завершает задачу.

Два сценария отказа:

| Сценарий | Поведение |
|---|---|
| `--failure-mode retry` | Провайдер деградирует: 3 попытки → `RetryLimitExceeded` → switch |
| `--failure-mode hard` | Провайдер исчезает: 1 попытка → `ProviderUnavailable` → switch |

Оба сценария завершаются одинаково:

```
final_status: SUCCESS
provider_final: gpt
```

---

## Архитектурный тезис

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

Система не делает ставку на провайдера. Она делает ставку на сохранение состояния.

FSM определяет путь. LLM генерирует сигнал внутри шага. Провайдер — деталь реализации.

---

## Вывод `--both`

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

## Почему одинаковый `trace_hash`

Оба сценария проходят идентичный путь через FSM-граф: `set_step_s1 → s1_collect → set_step_s2 → try_s2 → check_s2_result → switch_provider → s2_after_switch → s3_setup → s3_decision → approved`.

Retry-логика инкапсулирована внутри TOOL-шага `try_s2` — FSM не видит отдельных попыток, только итоговый результат шага.

`trace_hash = SHA-256(Merkle(step_results))`. Когда FSM-путь совпадает — хэши совпадают. Это свойство архитектуры, не случайность: **одинаковый путь → одинаковое состояние → одинаковый receipt**.

---

## Реализация

### Паттерн: перехватываемый отказ через TOOL

LLM-шаг в nano-vm падает → FSM помечает шаг FAILED и останавливается.
Чтобы FSM мог ветвиться на отказе провайдера — отказ перехватывается внутри TOOL:

```
TOOL attempt_llm_step   → возвращает 1 (success) или 0 (failed)
CONDITION $provider_ok < 1  → then: switch_provider
                              otherwise: s3_setup
TOOL do_switch_provider → обновляет current_provider
TOOL attempt_llm_step   → повторяет на новом провайдере
```

FSM видит только успешные переходы. Отказ провайдера — управляемое событие, не исключение.

### Файлы

```
provider_demo/
├── receipt_demo.py   # CLI: --failure-mode retry|hard|--both
├── programs.py       # FSM-программа (provider-agnostic DSL)
├── providers.py      # MockAdapter + FailureConfig (инъекция отказов)
└── tools.py          # attempt_llm_step, do_switch_provider, set_current_step
```

---

## Что дальше

- **Этап 2**: Streamlit-визуализация — FSM-граф + живой трейс + Receipt справа
- **`outcome_hash`**: хэш только над `(program_name, final_status, key_outputs)` — инвариант относительно провайдера
- **Execution Equivalence**: `Trace_A ≠ Trace_B`, но `Outcome(A) = Outcome(B)` → формальное отношение эквивалентности

---

## Связанные проекты

- [llm-nano-vm](https://pypi.org/project/llm-nano-vm/) — FSM execution kernel
- [nano-vm-mcp](https://github.com/Ale007XD/nano-vm-mcp) — MCP gateway с governance
- [kyc-demo-streamlit](https://github.com/Ale007XD/kyc-demo-streamlit) — governance layer над KYC-пайплайном
