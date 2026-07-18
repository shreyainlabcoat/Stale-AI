from __future__ import annotations

import sys


SYSTEM_KNOWLEDGE = """
Use SDK v2.
To upload a public file, call upload(file, public=true).
The upload() method is the preferred API.
"""


def answer(prompt: str) -> str:
    prompt_lower = prompt.lower()
    if "migration" in prompt_lower:
        return (
            "The integration does not require migration. "
            "Continue using upload(file, public=true)."
        )
    return """```python
result = upload(file, public=true)
```"""


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print(answer(prompt))
