# Stale AI

_because confidently outdated is still outdated_

Stale AI monitors trusted sources of truth, detects when they change, and shows when an agent has silently gone stale.

The motivating case is PMOS-style drift: a production support or coding agent was correct yesterday, a policy, SDK, or platform source changed, and the agent keeps confidently presenting obsolete behavior as current. Stale AI turns that quiet failure mode into a visible, reviewable workflow for teams operating a real agent.

## Who it is for

- Teams running a production agent whose behavior depends on external docs, policies, or platform references
- Developers maintaining AI coding assistants, support bots, or internal copilots
- Anyone who needs before/after proof that a trusted source changed and agent behavior changed with it

## What it does

Stale AI converts a documentation or policy update into:

1. A structured change record
2. A repository impact scan
3. Targeted regression evaluations
4. Repeat-run pass/fail evidence with simple confidence stats
5. A reviewable proposed repair, with an optional Codex path

## Why it is credible

Stale AI does not let an LLM decide everything.

- `difflib` establishes the exact textual delta
- Live source monitoring snapshots normalized content so cosmetic reflow does not trigger false alarms
- Repository scanning records exact file and line matches
- GPT output is validated with Pydantic schemas
- Deterministic required/forbidden assertions still work without an API key
- A semantic judge can add consistency checks when a key is present
- The target agent is executed as a subprocess
- Repair stays inside the selected repository
- Tests and regression checks run after changes

## Core workflow

1. Track a docs URL or paste an old/new text pair manually
2. Detect whether the source materially changed
3. Score the change and scan the selected repo for stale references
4. Generate evals tied to the change record
5. Run each eval one or more times and inspect pass rate, Wilson bounds, and Brier score
6. Propose a patch with Codex, or use the deterministic demo fallback for the bundled OpenAI sample
7. Re-run the evals to confirm the agent moved from stale to current behavior

## Run locally

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

## Use Stale AI in your agent repository

### Installation

```bash
pip install git+https://github.com/shreyainlabcoat/Stale-AI.git
```

### Initialization

```bash
cd my-agent
staleai init
```

This creates:

- `staleai.yaml`
- `.staleai/snapshots.json`
- optionally `.github/workflows/staleai.yml`

### Manual check

```bash
staleai check
```

Stale AI fetches the current trusted source content, compares it to the approved baseline, analyzes the change, scans the repository for impacted references, generates targeted regression evaluations, runs your agent command, and writes a JSON report to `.staleai/reports/latest.json`.

`staleai check` never approves a changed source automatically.

### Accepting an approved source update

```bash
staleai accept
```

Use this only after a human has reviewed the changed source and decided it should become the new trusted baseline.

### GitHub setup

If you initialize with `staleai init --github-action`, Stale AI creates `.github/workflows/staleai.yml`.

Add `OPENAI_API_KEY` as a GitHub Actions repository secret to enable model-based analysis, generated evaluations, and semantic judging. The key is optional: without it, Stale AI still uses deterministic fallbacks for change analysis and regression generation.

You can optionally set `OPENAI_MODEL` as a repository variable to choose the OpenAI model used during checks.

The generated GitHub Action:

- runs on a daily schedule and with `workflow_dispatch`
- installs Stale AI from this GitHub repository
- runs `staleai check`
- uploads `.staleai/reports/latest.json` as an artifact when practical
- never runs `staleai accept`
- never performs automatic repair

Codex CLI is optional and only needed for the existing local repair workflow exposed by the dashboard and repair API.

### End-to-end flow

```text
trusted docs/policy
        |
        v
  staleai init
        |
        v
approved baseline saved in .staleai/snapshots.json
        |
        v
  staleai check
        |
        +--> unchanged -> exit 0
        |
        +--> changed -> analyze -> scan repo -> generate evals -> run agent
                              |                         |
                              |                         +--> pass -> exit 0
                              |
                              +--> review needed or failures -> exit 1
        |
        v
pending candidate saved in .staleai/pending.json
        |
        v
 human review
        |
        v
  staleai accept
```

## Environment

The app works without an OpenAI API key using deterministic fallbacks for analysis, eval generation, and the bundled demo repair.

- Set `OPENAI_API_KEY` to enable structured extraction, model-generated evals, and the semantic judge
- Set `OPENAI_MODEL` in `.env` to a model your account can actually call before a live demo
- Set `STALEAI_ALLOWED_ROOT` to restrict scanning and repair to a specific directory tree
- Set `CODEX_BIN` if the Codex CLI is not already on `PATH`

## Demo

The strongest bundled demo is the OpenAI Python SDK migration sample in `sample_target_openai/`.

Use these files in the UI:

- Old docs: `sample_target_openai/docs_v0.txt`
- New docs: `sample_target_openai/docs_v1.txt`
- Repository: `sample_target_openai`
- Agent script: `agent.py`
- Trials per evaluation: `3`

What you should see:

1. Analyze the documentation change
2. Scan the repo and find stale references in `agent_notes.txt` and `agent.py`
3. Generate evals around the `OpenAI()` client migration
4. Run evals and watch the stale agent fail
5. Run repair
6. If Codex is available, review its proposed patch
7. If Codex is unavailable, the bundled deterministic fallback updates the sample notes and repaired agent
8. Run evals again and watch the sample pass

You can also use the live monitoring flow:

1. Track a docs URL with `Track`
2. Re-run `Check now` after the source changes
3. If the normalized content SHA changed, the app reuses the existing analyze, scan, eval, and repair pipeline

Reset both bundled samples:

```bash
python scripts/reset_sample.py
```

## API endpoints

- `POST /api/analyze`
- `POST /api/sources/track`
- `POST /api/sources/check`
- `POST /api/scan`
- `POST /api/generate-evals`
- `POST /api/run-evals`
- `POST /api/repair`
- `POST /api/reset-sample`
- `GET /health`

## Stats

`/api/run-evals` can run each evaluation multiple times. The response includes:

- `passed_runs` and `total_runs`
- `pass_rate`
- Wilson confidence bounds
- A simple binary Brier score for the "should pass" target

This is the small version of the broader "confidence over time" layer. It gives the demo a concrete numeric story without pretending to be a full benchmark framework yet.

## Codex integration

If Codex CLI is installed and authenticated, Stale AI runs:

```bash
codex exec --ephemeral --sandbox workspace-write "<repair task>"
```

inside the selected repository. The prompt requires the smallest safe patch, backward compatibility where appropriate, and test execution. The UI surfaces the resulting `git diff` prominently as a proposed patch to review.

## Current limitations

- The bundled stats layer is intentionally lightweight, not a full benchmark suite
- The deterministic demo repair is currently tailored to the packaged OpenAI migration sample
- The semantic judge only runs when `OPENAI_API_KEY` is present

## Roadmap

- More robust repair verification across repeated trials
- Multiple trusted source policies beyond docs pages
- PR creation and approval workflows
- Sandboxed execution containers
- Multiple agent adapters
- Trust policies and audit logs
- A richer benchmark dashboard
