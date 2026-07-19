from pathlib import Path
import shutil

root = Path(__file__).resolve().parents[1]
shutil.copyfile(
    root / "sample_target" / "original_agent.py",
    root / "sample_target" / "agent.py",
)
openai_root = root / "sample_target_openai"
if openai_root.exists():
    shutil.copyfile(openai_root / "original_agent.py", openai_root / "agent.py")
    shutil.copyfile(
        openai_root / "original_agent_notes.txt",
        openai_root / "agent_notes.txt",
    )
print("Sample agents reset.")
