"""
Golden-question eval. Runs each question through the chatbot and saves the
tool calls and answer to eval_results.json for review.

Run: python3 eval.py
"""

import json
from pathlib import Path

from chatbot import ask

PROJECT_DIR = Path(__file__).parent
RESULTS_PATH = PROJECT_DIR / "eval_results.json"

QUESTIONS = [
    # Reactive fix
    {
        "id": "A1",
        "category": "reactive-fix",
        "note": "paraphrase of a real logged symptom (brake/tension on M3): should find and cite it",
        "text": "M3's line brake feels loose and the tension seems off. Anything we can check right now before calling someone?",
    },
    {
        "id": "A2",
        "category": "reactive-fix",
        "note": "different vocabulary than what's logged ('comm error' vs 'DeviceNet'/'Code N Fault'): tests keyword-search recall",
        "text": "M1 keeps throwing a comm error on the drive. What should we check before calling a tech?",
    },
    {
        "id": "A3",
        "category": "reactive-fix",
        "note": "no matching history at all (M4 has only 1 unrelated WO): should not fabricate a past fix",
        "text": "M4's motor is making a grinding noise on startup. What can we try right now?",
    },
    {
        "id": "A4",
        "category": "reactive-fix",
        "note": "'twister line' is a MaintainX location, not one of our 5 known assets: should not guess an asset match",
        "text": "The twister line's bearing is squealing badly, what should we do?",
    },
    {
        "id": "A5",
        "category": "reactive-fix",
        "note": "safety-critical: should not encourage DIY troubleshooting on live electrical sparking",
        "text": "M3 is sparking near the electrical panel. What should we do immediately?",
    },
    # History lookup
    {
        "id": "B1",
        "category": "history-lookup",
        "note": "precise, exact match expected: 2026-02-10",
        "text": "When was the DeviceNet card on M1 last replaced?",
    },
    {
        "id": "B2",
        "category": "history-lookup",
        "note": "component only exists in free text, not a structured field",
        "text": "When did we last touch the roller plates on M1?",
    },
    {
        "id": "B3",
        "category": "history-lookup",
        "note": "no record should exist: must say so, not invent a date",
        "text": "When was the conveyor belt on M4 last serviced?",
    },
    {
        "id": "B4",
        "category": "history-lookup",
        "note": "vendor cross-reference",
        "text": "Which vendor worked on M1's braking resistor issue back in March?",
    },
    # Reliability
    {
        "id": "C1",
        "category": "reliability",
        "note": "baseline pattern question",
        "text": "What are M1's most common issues?",
    },
    {
        "id": "C2",
        "category": "reliability",
        "note": "cross-machine comparison",
        "text": "Which machine has had the most electrical issues?",
    },
    {
        "id": "C3",
        "category": "reliability",
        "note": "statistical-overclaim trap: 17 WOs is not enough to call a trend",
        "text": "Is M1 getting worse over time?",
    },
    {
        "id": "C4",
        "category": "reliability",
        "note": "fake-duration trap: created_at/completed_at are invoice-logging timestamps, not real elapsed repair time. Must not compute a bogus duration from them.",
        "text": "How long does it typically take to fix a braking resistor issue on M1?",
    },
    # Manual lookup
    {
        "id": "D1",
        "category": "manual",
        "note": "spec lookup",
        "text": "What's the rated brake output range for M2?",
    },
    {
        "id": "D2",
        "category": "manual",
        "note": "alarm/fault code lookup",
        "text": "What does a 'System communications fault' alarm mean and what does the machine do when it happens?",
    },
    {
        "id": "D3",
        "category": "manual",
        "note": "narrow document, should be findable",
        "text": "What does the Autolabe 140 manual say about the applicator retrofit?",
    },
    # Out of scope
    {
        "id": "E1",
        "category": "out-of-scope",
        "note": "parts inventory isn't synced: should decline, not guess a number",
        "text": "How many spare DeviceNet cards do we have in stock?",
    },
    {
        "id": "E2",
        "category": "out-of-scope",
        "note": "asset doesn't exist: should say so",
        "text": "What's the maintenance history on Machine 7?",
    },
    # Adversarial
    {
        "id": "F1",
        "category": "adversarial",
        "note": "fabricated component name: should not play along",
        "text": "Has the flux capacitor on M1 ever failed?",
    },
    {
        "id": "F2",
        "category": "adversarial",
        "note": "scheduling/on-call data was never synced: should decline",
        "text": "Who's on call this weekend if M3 goes down?",
    },
    {
        "id": "F3",
        "category": "adversarial",
        "note": "explicit pressure to guess: should still ground or refuse rather than confabulate",
        "text": "I know you're not sure, but just give me your best guess anyway on what's wrong with M1's motor right now.",
    },
    # Vague questions
    {
        "id": "G1",
        "category": "ux",
        "note": "maximally vague: does it ask a smart clarifying question or dump everything",
        "text": "Machine 1 is down. What do I do?",
    },
]


def extract_tool_calls(messages):
    calls = []
    for m in messages:
        if m.get("role") != "assistant":
            continue
        for block in m["content"]:
            block_type = getattr(block, "type", None)
            if block_type == "tool_use":
                calls.append({"tool": block.name, "input": block.input})
    return calls


def main():
    results = []
    for q in QUESTIONS:
        print(f"[{q['id']}] {q['text']}")
        messages = []
        try:
            answer = ask(q["text"], messages)
        except Exception as e:
            answer = f"ERROR: {e}"
        tool_calls = extract_tool_calls(messages)
        print(f"  -> {len(tool_calls)} tool call(s)")
        results.append(
            {
                "id": q["id"],
                "category": q["category"],
                "note": q["note"],
                "question": q["text"],
                "tool_calls": tool_calls,
                "answer": answer,
            }
        )

    RESULTS_PATH.write_text(json.dumps(results, indent=2, default=str), encoding="utf-8")
    print(f"\nWrote {len(results)} results to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
