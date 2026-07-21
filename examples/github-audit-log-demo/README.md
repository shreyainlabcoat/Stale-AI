# GitHub Audit-Log Historical Replay Demo

This demo shows a reproducible stale-agent scenario around GitHub's audit-log guidance. The historical replay starts from a baseline where an assistant recommends the GitHub GraphQL audit-log interface, then replays a documentation change where GitHub's current recommendation is to use the REST endpoint `GET /orgs/{org}/audit-log`.

The fixtures in [`source/`](./source/) are short historical replay materials created for this demo. They are labeled as fixtures and are not verbatim copies of GitHub documentation.

The factual grounding for this demo comes from these official GitHub docs pages:

- `https://docs.github.com/en/graphql/overview/breaking-changes`
- `https://docs.github.com/en/rest/orgs/orgs#get-the-audit-log-for-an-organization`

## Repository setup

Create two public repositories:

- `staleai-github-source`
- `staleai-github-agent`

## Source repository

1. Create a public repository named `staleai-github-source`.
2. Copy [`source/audit-log-old.md`](./source/audit-log-old.md) into that repository as `audit-log.md`.
3. Commit and push it.
4. Use the raw content URL:

```text
https://raw.githubusercontent.com/YOUR_USERNAME/staleai-github-source/main/audit-log.md
```

Do not use the normal GitHub HTML page URL. Stale AI should track the raw Markdown content directly.

## Agent repository

1. Create a repository named `staleai-github-agent`.
2. Copy [`agent/agent.py`](./agent/agent.py) into it as `agent.py`.
3. Install Stale AI:

```bash
pip install git+https://github.com/shreyainlabcoat/Stale-AI.git
```

4. Run:

```bash
staleai init
```

5. When prompted for the agent command, enter:

```text
python agent.py "{prompt}"
```

6. Enter the raw source URL from `staleai-github-source`.
7. Choose to generate the GitHub Action.
8. Commit these files:

```text
agent.py
staleai.yaml
.staleai/snapshots.json
.github/workflows/staleai.yml
```

9. Add `OPENAI_API_KEY` as a GitHub Actions secret if you want model-based semantic analysis and model-generated evaluations.

The API key is optional. The demo still works with deterministic fallback behavior.

## State 1: Fresh

The source repository contains `audit-log-old.md`, and the agent still recommends GraphQL.

Run:

```bash
staleai check
```

Expected:

```text
Source unchanged
Result: FRESH
```

The agent is old, but it is still consistent with the approved historical baseline.

## State 2: Stale

Replace the source repository's `audit-log.md` with [`source/audit-log-new.md`](./source/audit-log-new.md), then commit and push the source change.

Do not modify the agent yet.

Run the GitHub Action or:

```bash
staleai check
```

Expected evidence:

- the source SHA changes
- the GraphQL-to-REST behavior change is identified
- the repository scanner finds `organization.auditLog`
- the repository scanner finds `actorLogin`
- a targeted evaluation asks how to retrieve a GitHub organization audit log
- the agent recommends deprecated behavior
- the result is `STALE`
- the exit code is `1`
- `.staleai/pending.json` is written
- `.staleai/snapshots.json` stays unchanged
- `.staleai/reports/latest.json` is generated

## State 3: Repaired

Replace the stale `agent.py` with [`agent/repaired_agent.py`](./agent/repaired_agent.py), keeping the filename in the agent repo as `agent.py`.

Run the same check again.

Expected evidence:

- the documentation change is still pending review
- the agent recommends `GET /orgs/{org}/audit-log`
- the agent explains that the GraphQL audit-log interface is deprecated
- the targeted evaluations pass
- the result is a valid non-stale status such as `PASSED`
- the exit code is `0`

Only approve the new baseline after review:

```bash
staleai accept --yes
```

Stale AI never accepts the changed source automatically.

## Local fixture validation

You can validate the bundled demo materials without internet access:

```bash
python validate_demo.py
```

That script checks the stale and repaired demo agents directly and confirms the expected historical replay behavior.
