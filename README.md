# 🧭 Trailblazer

**Follow the trail from an issue to its root cause.**

Trailblazer is a verified codebase investigation tool and coding agent skill. When assigned an issue in an unfamiliar or massive repository, Trailblazer traces only the relevant code path, validates findings directly against the repository's git tree, and compiles a clean, interactive local dashboard on `http://localhost:4200`.

---

## ✨ Why Trailblazer?

- **Zero-Token Hallucination Protection**: Every code snippet and claim is cross-validated by a strict local Python checker (`compile.py`) against real lines in the repository.
- **Zero-Dependency Runtime**: No Node.js, npm, or heavy framework required on the user's machine. Operates entirely with the Python 3.8+ standard library and modern, responsive vanilla web components.
- **Token-Optimized Architecture**: Designed with local pre-filtering to save up to 70% of LLM token expenditure compared to traditional agent searches.
- **AI Policy Radar**: Automatically detects and surfaces repository contribution policies regarding AI tools.
- **Clean Invariant Guardrails**: Clear separation of *what must remain true* versus *what is permitted to change*.

---

## 🚀 Quick Start

### 1. Run without an agent (Demo)
You can test the compiler and preview the interactive dashboard immediately:
```bash
python3 scripts/compile.py examples/example-trace.json --serve
```
This validates `example-trace.json`, compiles `index.html`, and launches the local browser server.

### 2. Using with your Coding Agent
Install Trailblazer into your agent's skills directory:
```bash
# Example for Claude Code / Antigravity / Codex:
git clone https://github.com/<your-username>/trailblazer ~/.agents/skills/trailblazer
```

Then in any project repository, simply prompt your agent:
```text
/trailblazer explain issue #142
```
or
```text
Explain issue https://github.com/owner/repo/issues/142 using trailblazer
```

The agent will investigate, output `.tbz/<issue-id>/trace.json`, compile it, and present a concise summary with a link to `http://localhost:4200`.

---

## 📂 Repository Structure

```
trailblazer/
├── SKILL.md                # Agent instruction & prompt contract
├── package.json            # Skill discovery and CLI configuration
├── scripts/
│   └── compile.py          # Python standard library validator & compiler
├── assets/
│   └── template.html       # Self-contained, responsive dashboard
├── references/
│   └── trace-schema.md     # trace.json schema definition
└── examples/
    └── example-trace.json  # Comprehensive reference example
```

---

## 🛠️ CLI Options for `compile.py`

```text
python3 scripts/compile.py TRACE_JSON [--repo PATH] [--out DIR] [--serve] [--port N] [--check-only]

Options:
  --repo PATH     Cross-validate code snippets and line numbers against a local repository clone
  --out DIR       Custom destination directory for generated index.html
  --serve         Start local HTTP server and open browser
  --port N        Specify starting port (default: 4200)
  --no-open       Do not auto-launch system browser
  --check-only    Validate trace.json without rendering HTML output
```

---

## 📄 License
MIT © 2026 Trailblazer Contributors
