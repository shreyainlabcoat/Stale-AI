# Stale AI

_because confidently outdated is still outdated_

Stale AI converts a trusted documentation change into:

1. A structured change record
2. A repository impact scan
3. Targeted regression evaluations
4. Before/after pass–fail evidence
5. An optional Codex repair of the affected repository

The MVP is intentionally narrow: **developer documentation changes that can make an AI coding or support agent produce obsolete code**.

## Why the implementation is credible

Stale AI does not let an LLM decide everything.

- `difflib` establishes the exact textual delta.
- Repository scanning records exact file and line matches.
- GPT-5.6 classifies the meaning of the change into a typed schema.
- Evaluations use deterministic required/forbidden assertions.
- The target agent is executed as a subprocess.
- Codex edits only the selected repository.
- Existing tests and new regression tests are run after repair.

## Run

From the project root:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

macOS/Linux:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

The application works without an OpenAI API key using a deterministic sample-oriented fallback. Add `OPENAI_API_KEY` to use GPT-5.6 structured extraction and eval generation.

## Demo flow

Use these files in the UI:

- Old docs: `sample_target/docs_v2.txt`
- New docs: `sample_target/docs_v3.txt`
- Repository: absolute path to `sample_target`
- Agent script: `agent.py`

Then:

1. Analyze the documentation change.
2. Scan the repository.
3. Generate regression evaluations.
4. Run evaluations. The old agent should fail.
5. Run Codex repair.
6. Run evaluations again. The repaired agent should pass.

Reset the sample:

```bash
python scripts/reset_sample.py
```

## Codex integration

Install Codex CLI and authenticate it. Stale AI runs:

```bash
codex exec --ephemeral --sandbox workspace-write "<repair task>"
```

inside the selected repository. The prompt requires the smallest patch, preservation of compatibility, and test execution. Codex remains optional so the app can still be installed and demonstrated without it.

## API endpoints

- `POST /api/analyze`
- `POST /api/scan`
- `POST /api/generate-evals`
- `POST /api/run-evals`
- `POST /api/repair`
- `POST /api/reset-sample`
- `GET /health`

## Production extensions

After the hackathon:

- GitHub App installation instead of local paths
- Changelog polling and version snapshots
- Pull-request creation
- Sandboxed execution containers
- Multiple agent adapters
- Source trust policies
- Human approval and audit logs
- Benchmark dashboard
