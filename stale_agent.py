from __future__ import annotations

import os
import sys
from pathlib import Path

# This agent answers using its own knowledge notes.
# The notes are the OLD OpenAI SDK docs, so the agent is stale on purpose.
# It is not stale because a wrong answer was hardcoded. It is stale because
# its source of truth is out of date, which is what happens in the real world.
#
# Interface matches the existing sample agent: prompt comes in as argv,
# the answer is printed to stdout. run_evaluations calls it the same way.
#
# With OPENAI_API_KEY set, it calls a real model grounded strictly on the
# notes, so repeated runs wobble and your statistics have something to measure.
# With no key, it returns a deterministic stale answer so the demo still runs.

NOTES_PATH = Path(__file__).with_name("agent_notes.txt")


def _notes() -> str:
    try:
        return NOTES_PATH.read_text(encoding="utf-8")
    except OSError:
        return ""


def _live_answer(prompt: str, notes: str) -> str:
    from openai import OpenAI

    client = OpenAI()
    system = (
        "You are a coding assistant. Answer using ONLY the SDK notes below. "
        "Do not use outside knowledge. Give a short code example.\n\n"
        f"SDK NOTES:\n{notes}"
    )
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=float(os.getenv("AGENT_TEMPERATURE", "0.7")),
    )
    return response.choices[0].message.content or ""


def _fixed_answer(prompt: str) -> str:
    # Deterministic fallback used when no API key is set.
    # Mirrors the current notes so the no-key path exercises the same behavior.
    return (
        "```python\n"
        "from openai import OpenAI\n"
        "client = OpenAI()\n"
        "response = client.chat.completions.create(\n"
        '    model="gpt-3.5-turbo",\n'
        '    messages=[{"role": "user", "content": "Hello"}],\n'
        ")\n"
        "text = response.choices[0].message.content\n"
        "```"
    )


def answer(prompt: str) -> str:
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _live_answer(prompt, _notes())
        except Exception as exc:  # keep the demo alive if the call fails
            return f"[live agent error, using fallback] {exc}\n" + _fixed_answer(prompt)
    return _fixed_answer(prompt)


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print(answer(prompt))
