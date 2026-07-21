# Stale AI

[![Tests](https://github.com/shreyainlabcoat/Stale-AI/actions/workflows/tests.yml/badge.svg)](https://github.com/shreyainlabcoat/Stale-AI/actions/workflows/tests.yml)

_because confidently outdated is still outdated_

Stale AI monitors trusted sources of truth, detects when they change, and shows when an agent has silently gone stale.

The motivating case is PMOS-style drift: a production support or coding agent was correct yesterday, a policy, SDK, or platform source changed, and the agent keeps confidently presenting obsolete behavior as current. Most teams find out about this kind of drift from a support ticket or an incident, not from a test suite. Stale AI turns that quiet failure mode into a visible, reviewable workflow, with reproducible before/after evidence that a specific documentation change broke a specific agent behavior.

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

## AI workflow: GPT-5.6 + Codex

Stale AI is built around a deliberate split between deterministic checks and model calls, so every model call has a narrow, verifiable job:

| Stage | Model | What it does | File |
|---|---|---|---|
| Source-change analysis | GPT-5.6 | Extracts an old/new documentation diff into a strict, Pydantic-validated `ChangeCard` (change type, deprecated/replacement terms, materiality, breaking signal) | [`app/analyzer.py`](app/analyzer.py) |
| Evaluation generation | GPT-5.6 | Turns the change record and repository matches into targeted regression prompts with exact required/forbidden substrings | [`app/evals.py`](app/evals.py) |
| Semantic judge | GPT-5.6 | Adds a consistency check on top of the deterministic substring/return-code grading, catching cases where an agent presents obsolete behavior without tripping a literal string match | [`app/evals.py`](app/evals.py) |
| Repair | Codex CLI | Runs `codex exec --ephemeral --sandbox workspace-write` inside the selected repository with a generated repair prompt, and surfaces the resulting `git diff` for human review | [`app/codex_runner.py`](app/codex_runner.py) |

None of these calls are free-form. Analysis and eval generation return schema-validated output; the judge only ever adds a pass/fail signal on top of grading that already happened deterministically; Codex never runs without an explicit `run_codex=True` and its output is a diff to review, not an auto-applied change. If a model call fails or no API key is present, every stage has a deterministic fallback so the pipeline still produces a usable result — see [Environment](#environment) and [Fast demo mode](#fast-demo-mode).

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

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Optional. Enables structured extraction, model-generated evals, and the semantic judge. |
| `OPENAI_MODEL` | Model used for analysis, eval generation, and the judge. Set this to a model your account can actually call before a live demo. |
| `STALEAI_ALLOWED_ROOT` | Restricts repository scanning and repair to a specific directory tree. Defaults to the project directory. |
| `CODEX_BIN` | Codex executable, if it is not already on `PATH`. |
| `STALEAI_FAST_DEMO` | See [Fast demo mode](#fast-demo-mode) below. |
| `STALEAI_SEMANTIC_JUDGE` | Independently enable/disable the semantic judge without turning on the rest of fast demo mode. Defaults to on. Fast demo mode always forces it off regardless of this setting. |

## Fast demo mode

The full evaluation loop is thorough but sequential: 3 evaluations x 3 runs each means 1 analysis call, 1 eval-generation call, up to 9 live agent calls, and up to 9 semantic-judge calls for a single evaluation run. That is the right default for production freshness checks, but it makes a live demo slow and burns API calls on every repeat run.

Set `STALEAI_FAST_DEMO=true` to keep the meaningful model-powered parts and cut everything repetitive:

1. `runs_per_eval` is forced to 1, regardless of what the UI or API request asks for.
2. The semantic judge is skipped entirely.
3. Grading still runs the existing deterministic checks: required substrings, forbidden substrings, and process return code.
4. The bundled `sample_target_openai` agent answers from its notes-based deterministic response instead of making a live OpenAI call. This is a direct skip, not a wait-then-fallback: the agent never attempts the live call, so a slow or failing request can't stall the demo.
5. Source-change analysis and evaluation generation still call the OpenAI API when `OPENAI_API_KEY` is set — those two calls are the meaningful, one-time model work worth keeping.
6. With `STALEAI_FAST_DEMO` unset or `false`, behavior is unchanged from the full production flow.

The dashboard shows a `FAST DEMO MODE` badge whenever it's active (fetched from `GET /api/config`), and `POST /api/run-evals` reports `fast_demo_mode` in its response so this is never a silent behavior change.

Measured on this repository's bundled OpenAI-migration demo (reset -> analyze -> scan -> generate 3 evals -> run before repair -> repair -> run after repair), with a real `OPENAI_API_KEY`:

| | Full mode | Fast demo mode |
|---|---|---|
| Real OpenAI API calls | 38 (1 analyze + 1 eval-gen + 18 judge + 18 live agent, across both evaluation runs) | 2 (analyze + eval-gen only) |
| Wall-clock time | 185.6s | 6.8s |
| Result | 0/3 -> repaired -> 3/3 | 0/3 -> repaired -> 3/3 |

Use `STALEAI_SEMANTIC_JUDGE=false` on its own if you just want to drop judge calls (for cost or determinism) without forcing `runs_per_eval` down or touching the sample agent.

## Demo

The strongest bundled demo is the OpenAI Python SDK migration sample in `sample_target_openai/`.

Use these files in the UI:

- Old docs: `sample_target_openai/docs_v0.txt`
- New docs: `sample_target_openai/docs_v1.txt`
- Repository: `sample_target_openai`
- Agent script: `agent.py`
- Trials per evaluation: `3` (or `1` automatically if `STALEAI_FAST_DEMO=true`)

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

## Real-world demonstration: GitHub audit-log migration

GitHub's audit-log guidance provides a good historical replay example for Stale AI. An assistant can keep recommending the older GraphQL audit-log interface long after the official guidance has moved to the REST endpoint `GET /orgs/{org}/audit-log`.

The included GitHub audit-log demo shows that workflow end to end: Stale AI detects the documentation change, finds stale repository references such as legacy audit-log identifiers, generates targeted regression evaluations, and marks the unchanged agent stale when it still recommends the deprecated path.

After the agent is repaired, the same evaluations pass without automatically accepting the new trusted source baseline. The full walkthrough is in [`examples/github-audit-log-demo/README.md`](examples/github-audit-log-demo/README.md).

## API endpoints

- `GET /api/config`
- `GET /api/demo/openai`
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
- `fast_demo_mode`, reflecting whether fast demo mode was active for that run

This is the small version of the broader "confidence over time" layer. It gives the demo a concrete numeric story without pretending to be a full benchmark framework yet.

## Codex integration

If Codex CLI is installed and authenticated, Stale AI runs:

```bash
codex exec --ephemeral --sandbox workspace-write "<repair task>"
```

inside the selected repository. The prompt requires the smallest safe patch, backward compatibility where appropriate, and test execution. The UI surfaces the resulting `git diff` prominently as a proposed patch to review.

## Testing

```bash
pytest
```

The suite covers the analyzer, scanner, eval runner, CLI, repair fallback, and fast demo mode (settings parsing, forced `runs_per_eval`, judge skip, and the sample agent's deterministic short-circuit) without requiring an OpenAI API key.

## Current limitations

- The bundled stats layer is intentionally lightweight, not a full benchmark suite
- The deterministic demo repair is currently tailored to the packaged OpenAI migration sample
- The semantic judge only runs when `OPENAI_API_KEY` is present and enabled

## Roadmap

- More robust repair verification across repeated trials
- Multiple trusted source policies beyond docs pages
- PR creation and approval workflows
- Sandboxed execution containers
- Multiple agent adapters
- Trust policies and audit logs
- A richer benchmark dashboard
