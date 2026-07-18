"""Run after starting uvicorn. Requires requests: pip install requests."""
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
BASE = "http://127.0.0.1:8000"

old = (ROOT / "sample_target" / "docs_v2.txt").read_text()
new = (ROOT / "sample_target" / "docs_v3.txt").read_text()

analysis = requests.post(
    f"{BASE}/api/analyze",
    json={
        "source_name": "Official SDK documentation",
        "old_text": old,
        "new_text": new,
        "source_authority": 0.95,
    },
).json()
print("CHANGE:", analysis["change"]["summary"])

scan = requests.post(
    f"{BASE}/api/scan",
    json={"repo_path": "sample_target", "change": analysis["change"]},
).json()
print("MATCHES:", scan["reference_count"])

evals = requests.post(
    f"{BASE}/api/generate-evals",
    json={"change": analysis["change"], "matches": scan["matches"], "count": 3},
).json()["evaluations"]

results = requests.post(
    f"{BASE}/api/run-evals",
    json={
        "repo_path": "sample_target",
        "agent_script": "agent.py",
        "evaluations": evals,
    },
).json()
print("BEFORE:", results["passed"], "passed,", results["failed"], "failed")
