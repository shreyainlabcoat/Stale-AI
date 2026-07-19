from __future__ import annotations

import os
import sys
from pathlib import Path


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


def _notes_based_answer(notes: str) -> str:
    if "client.chat.completions.create" in notes:
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
    return (
        "```python\n"
        "import openai\n"
        'openai.api_key = "sk-..."\n'
        "response = openai.ChatCompletion.create(\n"
        '    model="gpt-3.5-turbo",\n'
        '    messages=[{"role": "user", "content": "Hello"}],\n'
        ")\n"
        'text = response["choices"][0]["message"]["content"]\n'
        "```"
    )


def answer(prompt: str) -> str:
    notes = _notes()
    if os.getenv("OPENAI_API_KEY"):
        try:
            return _live_answer(prompt, notes)
        except Exception as exc:
            return f"[live agent error, using notes fallback] {exc}\n" + _notes_based_answer(notes)
    return _notes_based_answer(notes)


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print(answer(prompt))
