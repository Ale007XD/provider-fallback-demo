"""
nano-vm provider fallback demo.

Usage:
    python receipt_demo.py --failure-mode retry
    python receipt_demo.py --failure-mode hard
    python receipt_demo.py --both          # runs both and prints comparison table
"""
from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import os

# Ensure local modules are found
sys.path.insert(0, os.path.dirname(__file__))

from nano_vm.vm import ExecutionVM
from nano_vm.analyzer import TraceAnalyzer
from nano_vm.models import TraceStatus

from providers import FailureConfig, MockAdapter
from programs import build_program
from tools import init_tools, get_shared, TOOL_REGISTRY


def run_scenario(failure_mode: str) -> dict[str, object]:
    """Run one scenario, return summary dict."""
    failure_config = FailureConfig(mode=failure_mode)
    shared: dict[str, object] = {}

    # Adapter needs shared state ref to know current provider
    state_ref: dict[str, object] = {"current_provider": "claude", "current_step_id": "unknown"}
    adapter = MockAdapter(failure_config=failure_config, state_ref=state_ref)

    # Wire tools — they update state_ref in place
    init_tools(adapter)
    # Point adapter to the same shared dict that tools use
    adapter._state_ref = get_shared()  # type: ignore[attr-defined]

    program = build_program(failure_mode)
    vm = ExecutionVM(llm=adapter, tools=TOOL_REGISTRY)
    trace = asyncio.run(vm.run(program, context={"failure_mode": failure_mode}))

    analyzer = TraceAnalyzer(trace)
    receipt = analyzer.receipt()

    tool_shared = get_shared()

    # Build human-readable event log
    events: list[str] = []
    retry_log: list[tuple[str, str, int, str]] = tool_shared.get("retry_log", [])  # type: ignore[assignment]
    switch_event = tool_shared.get("switch_event")
    provider_switched = tool_shared.get("provider_switched", False)
    old_provider = "claude"
    new_provider = str(tool_shared.get("current_provider", "gpt"))

    for step_id_log, provider, attempt, result in retry_log:
        if result == "FAIL":
            if failure_mode == "retry":
                events.append(f"  {provider.upper()} failed ({attempt}/{failure_config.max_retries})")
            # hard mode: will show as EVENT below via switch block

    if provider_switched:
        if failure_mode == "hard":
            events.append(f"  EVENT: ProviderUnavailable ({old_provider.upper()})")
            events.append(f"  ACTION: switch_provider  {old_provider} → {new_provider}")
        else:
            events.append(f"\n  EVENT: {switch_event}")
            events.append(f"  ACTION: switch_provider  {old_provider} → {new_provider}")

    return {
        "mode": failure_mode,
        "trace_id": receipt.trace_id,
        "trace_hash": receipt.trace_hash,
        "final_status": str(receipt.final_status).split(".")[-1],
        "completed_steps": len([s for s in trace.steps if str(s.status).endswith("SUCCESS")]),
        "failed_steps": receipt.failed_steps,
        "retried_steps": receipt.retried_steps,
        "rejected_transitions": len(receipt.rejected_transitions),
        "provider_final": str(tool_shared.get("current_provider", "claude")),
        "switch_event": str(tool_shared.get("switch_event", "none")),
        "events": events,
        "rejected_details": [
            dataclasses.asdict(rt) for rt in receipt.rejected_transitions
        ],
    }


def print_scenario(result: dict[str, object]) -> None:
    mode = result["mode"]
    print(f"\n{'='*60}")
    print(f"=== Scenario: {mode.upper()} ===")
    print(f"{'='*60}")
    print("\nS1  collect_application   ✓  claude")

    events: list[str] = result["events"]  # type: ignore[assignment]
    print("\nS2  verify_income")
    for e in events:
        print(e)

    provider_final = result["provider_final"]
    print(f"\nS3  policy_decision       ✓  {provider_final.upper()}")
    print(f"    final_confirmation    ✓  {provider_final.upper()}")

    print("\nRECEIPT:")
    receipt_display = {
        "final_status": result["final_status"],
        "provider_final": result["provider_final"],
        "switch_event": result["switch_event"],
        "completed_steps": result["completed_steps"],
        "failed_steps": result["failed_steps"],
        "rejected_transitions": result["rejected_transitions"],
        "trace_hash": result["trace_hash"],
    }
    print(json.dumps(receipt_display, indent=2))

    if result["rejected_details"]:
        print("\nREJECTED TRANSITIONS:")
        for rt in result["rejected_details"]:  # type: ignore[union-attr]
            print(f"  step={rt['step_id']}  reason={rt['reason']}")


def print_comparison(r1: dict[str, object], r2: dict[str, object]) -> None:
    print(f"\n{'='*60}")
    print("=== COMPARISON TABLE ===")
    print(f"{'='*60}")
    headers = ["Metric", "Retry", "Hard Cutoff"]
    rows = [
        ["final_status",          r1["final_status"],          r2["final_status"]],
        ["completed_steps",       r1["completed_steps"],       r2["completed_steps"]],
        ["rejected_transitions",  r1["rejected_transitions"],  r2["rejected_transitions"]],
        ["switch_event",          r1["switch_event"],          r2["switch_event"]],
        ["provider_final",        r1["provider_final"],        r2["provider_final"]],
        ["trace_hash",
         str(r1["trace_hash"])[:12] + "...",
         str(r2["trace_hash"])[:12] + "..."],
    ]
    col = [28, 20, 20]
    print("  " + headers[0].ljust(col[0]) + headers[1].ljust(col[1]) + headers[2])
    print("  " + "-" * (col[0] + col[1] + col[2]))
    for row in rows:
        print("  " + str(row[0]).ljust(col[0]) + str(row[1]).ljust(col[1]) + str(row[2]))

    print(f"\n  {'─'*58}")
    print("  Different execution trace.  Same business outcome.")
    print(f"  {'─'*58}")
    print("\n  State survives. Providers don't.\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="nano-vm provider fallback demo")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--failure-mode", choices=["retry", "hard"])
    group.add_argument("--both", action="store_true")
    args = parser.parse_args()

    if args.both:
        r_retry = run_scenario("retry")
        r_hard = run_scenario("hard")
        print_scenario(r_retry)
        print_scenario(r_hard)
        print_comparison(r_retry, r_hard)
    else:
        r = run_scenario(args.failure_mode)
        print_scenario(r)


if __name__ == "__main__":
    main()
