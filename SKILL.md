---
name: trailblazer
description: Trace open source issues from symptom to source code root cause. Explains assigned issues through a verified, tabbed local dashboard (Executive Summary, Codebase Map, Interaction Flow, Annotated Code Trail, and Invariant Change Blueprint). Zero-npm dependency, verifiable against git history. Use whenever asked to explore, investigate, or explain an issue or bug report.
---

# Trailblazer

Trailblazer empowers engineers to understand a complex codebase issue in minutes. Instead of guessing or dumping hundreds of lines of code into conversation, you conduct a focused, verifiable investigation, record findings in `.tbz/<issue-id>/trace.json`, and compile an interactive, self-contained visual report.

---

## Operating Principles & Token Optimization

1. **Pre-filter Locally (Zero-Token Search)**
   - Use `git grep -n`, `rg`, or `git log --oneline` to pinpoint candidate lines and symbols before reading files.
   - Do not dump entire 500+ line files into context. Read only targeted line ranges around the candidate functions.
2. **Strict Invariant Guardrails**
   - Never recommend "loosening" or "ignoring" error checks without declaring what invariants must be maintained.
   - Separate verified claims from reasoned inferences (`evidence.level`).
3. **Clean Separation of Concerns**
   - The agent writes **data** (`trace.json`). The agent **never** writes page HTML.
   - The standalone `scripts/compile.py` validates the schema and compiles `assets/template.html`.
4. **Preserve Repository Integrity**
   - Never commit `.tbz/` to git history. Trailblazer data stays local in the developer's working directory.
   - Do not open PRs, push branches, or comment on issues unless specifically directed by the user.

---

## Investigation Workflow

### Phase 1: Input & Issue Intake
Accept any of the following input formats:
- Direct issue URL (GitHub, GitLab, Jira, etc.)
- Issue reference number (e.g. `#142` or `142` within an active git clone)
- Pasted issue description or stack trace

Use the appropriate CLI if available (`gh issue view <num> --json title,body,comments`) or read issue text. Extract:
- Core symptom and failure conditions
- Stack traces, error codes, and referenced symbols
- Issue category: `bug`, `flaky-test`, `feature`, `performance`, `security`, `refactor`, or `docs`

### Phase 2: Repository Orientation & AI Policy Radar
- Check for existing cache in `.tbz/repo-cache.json` to reuse orientation metadata.
- If fresh: inspect governance files (`CONTRIBUTING.md`, `README.md`, `.github/copilot-instructions.md`, `AGENTS.md`) for:
  - Project testing patterns (e.g., unit test runners, isolated vs e2e commands)
  - AI policy guidelines (`allowed`, `restricted`, `prohibited`, or `unspecified`)
- Store the AI policy findings in `aiPolicy`.

### Phase 3: Trace Construction (3 to 6 Stops)
- Trace the sequence from the initial entry point to where the behavior goes wrong:
  - `entry`: Where user/external trigger arrives (CLI command, HTTP handler, event hook)
  - `transit`: Intermediate routing or state evaluation
  - `origin`: The precise function or conditional where the defect originates
  - `patch`: The exact location where the fix should be introduced
- For each stop, note:
  - `file` and exact line numbers (`lineStart`, `lineEnd`)
  - Precise code snippet and pointer notes
  - 3-tier explanation: `simple` (plain English), `detailed` (technical mechanism), `deep` (architectural context or historical reason)

### Phase 4: Verification & Reproduction
- Attempt an isolated reproduction or inspect existing test cases.
- Classify reproduction level:
  - `reproduced-real`: Executed project's native test command and observed exact failure.
  - `reproduced-isolated`: Ran a standalone minimal script or unit test reproducing the mechanism.
  - `static-analysis`: Confirmed exclusively via static code and commit analysis.
  - `inferred`: Plausible mechanism deduced from documentation and logs without live execution.

### Phase 5: Emit `trace.json`
- Follow `references/trace-schema.md` strictly.
- Write output to `.tbz/<issue-id>/trace.json`.

### Phase 6: Compile & Launch
Run the validator and compiler from the repository root:
```bash
python3 <trailblazer-path>/scripts/compile.py .tbz/<issue-id>/trace.json --repo . --serve
```

- If errors are raised, adjust `trace.json` and re-compile.
- Ensure `.tbz/` is added to `.git/info/exclude` to avoid polluting the target repo's git status.
