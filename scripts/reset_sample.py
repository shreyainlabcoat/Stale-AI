from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
shutil.copyfile(
    root / "sample_target" / "original_agent.py",
    root / "sample_target" / "agent.py",
)
print("Sample agent reset.")
