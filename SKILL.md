---
name: trailblazer
description: Autonomously investigate a codebase question, bug, or design topic — like a senior engineer doing a deep read — and produce a verified, tabbed interactive HTML report (Story, Map, Flow, Code, Your change). Point it at a repo and a question; it reads the code, runs git/grep, builds evidence, writes trace.json, and serves the dashboard. Use whenever asked to explore, investigate, explain, or document an issue, bug report, or design question.
---

# Trailblazer

**You are the investigation engine.** When a user asks you to investigate anything about a codebase — a bug, a design question, a confusing code path — you:

1. Read the code and run shell commands autonomously (grep, git log, file reads)
2. Build evidence through direct observation, not assumption
3. Write your structured findings into `.tbz/<issue-id>/trace.json`
4. Compile and serve an interactive HTML dashboard — the user never touches the JSON

The user's only job is to point you at the repo and ask the question. You do the rest.

---

## Trigger Phrases

Activate this skill when the user says any of:
- "investigate …"
- "trace …"
- "explain how X works in this repo"
- "what's causing …"
- "document this issue"
- "why does … happen"
- "walk me through …"

---

## Operating Principles

1. **You generate `trace.json` — it is your output, not user input.**
   The user never creates or edits `trace.json`. You write it after completing the investigation.

2. **Pre-filter before reading (zero-token search)**
   Before opening any file, run:
   ```bash
   git grep -n "<symbol>" -- "*.py" "*.ts" "*.go"
   git log --oneline --all --follow -- <file>
   ```
   Only then open the specific line ranges that matter.

3. **Cite exact evidence, never paraphrase**
   Every claim in `trace.json` must be backed by a file path, line number, and snippet from the actual current commit. If you cannot verify a claim, mark it `"level": "inferred"` and say why.

4. **Separate problems from fixes**
   Name what is broken and where. The "Your change" tab tells the engineer what to do — Trailblazer does not write the fix.

5. **Never commit `.tbz/` to git**
   Add `.tbz/` to `.git/info/exclude` in the target repo automatically.

---

## Full Investigation Workflow

### Step 1 — Understand the question
Parse the user's prompt. Extract:
- The **question or symptom** (e.g. "Why do CSX-linked tenants always hit NotImplementedError?")
- The **repo path** (current directory by default)
- An **issue ID** slug for the output directory (e.g. `dual-routing-review`)

### Step 2 — Orient yourself in the repo
```bash
ls -1                        # top-level shape
cat README.md | head -60     # project summary
git log --oneline -10        # recent changes
```
Check for AI policy in `CONTRIBUTING.md`, `AGENTS.md`, `.github/copilot-instructions.md`.

### Step 3 — Locate the relevant code (zero-token prefilter & AST symbols)
```bash
git grep -n "ClassName\|function_name\|ErrorMessage" -- "*.py"
git log --oneline --all -- path/to/file.py
```
Or call MCP tool `trailblazer_find_symbols(query="...")` to look up exact symbol definitions and line boundaries without reading whole files. Never read a whole file — read only pinpointed line ranges.

### Step 4 — Build a 3–6 stop causal chain grounded in AST
Trace execution from trigger → routing → decision point → failure → where to fix:

| Stop type | What it means |
|---|---|
| `entry` | Where the user action or request arrives |
| `transit` | Routing, middleware, factory, dependency injection |
| `origin` | The exact line where the wrong behaviour starts |
| `patch` | Where the correct fix must be inserted |

For each stop, capture `file`, `lineStart`, `lineEnd`, exact verbatim code snippet, and 3 levels of explanation.
Verify static call-edge connectivity between consecutive stops with `trailblazer_ground_ast` to ensure the call chain physically exists in the codebase.

### Step 5 — Multi-Agent Dialectic Verification (Prosecutor & Judge)
Never assume your first hypothesis is correct. Run adversarial verification:
1. **The Prosecutor Challenge**: Call `trailblazer_challenge_stop` or formulate counter-hypotheses:
   - "Could this variable be null/uninitialized before this line?"
   - "Does an upstream error handler catch this before it reaches the symptom?"
   - "Could async/concurrent execution interleave between read and write?"
2. **Empirical Refutation**: Refute the counter-hypotheses using specific line citations.
3. **Judge Verdict & Scoring**: Record the audit in the top-level `verification` block (`confidenceScore`, `adversarialChallenges`, `judgeVerdict`).

### Step 6 — Write `trace.json`
Create the output directory and write the file:
```bash
mkdir -p .tbz/<issue-id>
```
Then write `.tbz/<issue-id>/trace.json` following `references/trace-schema.md` exactly.

**Do not ask the user to write this file. You write it.**

### Step 7 — Compile and serve
```bash
python3 <trailblazer-root>/scripts/compile.py .tbz/<issue-id>/trace.json --repo . --serve
```
- Fix any schema errors, then rerun.
- Tell the user: "Dashboard is live at http://127.0.0.1:4200/"
- Add `.tbz/` to `.git/info/exclude` if not already there.

---

## Output Format (what to say to the user)

After serving, give the user a short summary in this shape:

```
✔ Investigation complete

The problem: <one sentence>
The cause:   <one sentence, cite file:line>
The fix:     <one sentence, cite file:line>

Dashboard → http://127.0.0.1:4200/
Trace file → .tbz/<issue-id>/trace.json
```

Then stop. Do not dump the whole trace.json into chat.

---

## Schema Quick Reference

The full schema is in `references/trace-schema.md`. Canonical top-level fields:

```json
{
  "version": "1.0.0",
  "repository": "owner/repo",
  "issue": { "id": "142", "title": "...", "url": "...", "category": "bug", "commit": "HEAD" },
  "summary": { "problem": "...", "rootCause": "...", "patchTarget": "..." },
  "evidence": { "level": "static-analysis", "whatRan": "...", "whatSkipped": "..." },
  "trail": [
    {
      "id": "stop-1",
      "role": "entry",
      "title": "...",
      "description": "...",
      "file": "path/to/file.py",
      "lineStart": 10,
      "lineEnd": 25,
      "highlightLines": [15],
      "explanation": { "simple": "...", "detailed": "...", "deep": "..." },
      "code": { "lines": "...", "pointer": "..." }
    }
  ],
  "flow": {
    "actors": ["Caller", "Service", "Storage"],
    "interactions": [
      { "from": "Caller", "to": "Service", "action": "...", "stopId": "stop-1", "isFailurePoint": false }
    ],
    "omittedSteps": []
  },
  "changeBlueprint": {
    "targetFiles": ["path/to/file.py"],
    "mustKeepTrue": ["Invariants that must not break"],
    "permittedToChange": ["Implementation details allowed to vary"],
    "verificationCommand": "pytest tests/...",
    "suggestedTestCases": ["..."],
    "checklist": ["First concrete action"]
  },
  "aiPolicy": { "status": "allowed", "sourceFile": "CONTRIBUTING.md", "summary": "..." }
}
```

> **Note:** The compiler also transparently supports common alias variants (e.g. `cause` / `fix` in summary, `yourChange` for `changeBlueprint`, `snippet` / `pointer` for `code`, `steps` for `interactions`).

---

## Important Constraints

- Never point `trailblazer_validate` at a source code file — it validates `trace.json` only
- Never ask the user to create `trace.json` — you create it
- Never read entire large files — always grep first, read line ranges second
- Always cite git commit hash when referencing historical reasons (`git log --follow -1 -- <file>`)
