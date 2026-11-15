# 🧭 Trailblazer

### From assigned issue to verified root cause in minutes.
*A zero-dependency codebase investigation engine & visual dashboard for AI coding agents and engineers.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.8+](https://img.shields.io/badge/Python-3.8+-green.svg)](https://www.python.org/)
[![Zero Dependencies](https://img.shields.io/badge/Dependencies-Zero-brightgreen.svg)]()
[![MCP Compatible](https://img.shields.io/badge/MCP-Compatible-purple.svg)]()

---

## 💥 The Problem: "Huge Repo, Tiny Issue"

When assigned an issue or bug in a massive, unfamiliar codebase, developers and AI agents face the same struggle:

- **AI Agents burn thousands of tokens** dumping entire 500-line files into context, wandering down irrelevant directory trees, and guessing unverified line numbers.
- **Engineers spend hours** trying to orient themselves, understand cross-module interactions, and document their findings in scattered Slack threads or scratchpads.

**Trailblazer solves this.** It guides your AI agent (Claude Code, Cursor, Windsurf, etc.) to conduct a focused, verifiable investigation, validate every finding against actual repository lines at git `HEAD`, and produce a self-contained, interactive visual dashboard on `http://127.0.0.1:4200/`.

---

## ⚡ How It Works

```
 1. Ask a question          2. Autonomous Investigation          3. Verified Visual Dashboard
┌──────────────────┐       ┌──────────────────────────────┐     ┌────────────────────────────┐
│ "Why does token  │  ──▶  │ • Local zero-token grep      │ ──▶ │ 📖 Story (3-tier depth)     │
│  refresh fail on │       │ • Targeted line reads only   │     │ 🗺️ Architecture Map        │
│  reconnect?"     │       │ • Causal chain (3-6 stops)   │     │ 🔀 Flow (directional SVG)  │
│                  │       │ • Local compiler validation  │     │ 💻 Annotated Code Trail    │
└──────────────────┘       └──────────────────────────────┘     │ 🛡️ Invariant Blueprint     │
                                                                └────────────────────────────┘
```

---

## 🚀 Quick Start (30 Seconds)

### Option 1: MCP Server (Recommended)

Register Trailblazer as an MCP tool in your agent's configuration (`~/.claude.json`, Cursor MCP settings, or VS Code):

```json
{
  "mcpServers": {
    "trailblazer": {
      "command": "python3",
      "args": [
        "/absolute/path/to/trailblazer/mcp-server/server.py"
      ]
    }
  }
}
```

Then in any codebase, simply ask:
> *"Use Trailblazer to investigate why session authorization drops on socket reconnect."*

Your agent autonomously calls `trailblazer_start` → investigates → writes findings → validates → serves the dashboard on `http://127.0.0.1:4200/`.

---

### Option 2: Agent Skill

Install Trailblazer into your AI agent's skills directory:

```bash
git clone https://github.com/Ashrith-2001/trailblazer ~/.agents/skills/trailblazer
```

Prompt your agent:
```text
Investigate issue #142 using trailblazer in this repository.
```

---

### Option 3: Instant CLI Preview

Preview the interactive visual dashboard immediately with the bundled Nova Engine reference trace:

```bash
python3 scripts/compile.py examples/example-trace.json --serve
```

Opens `http://127.0.0.1:4200/` automatically in your browser.

---

## 🖥️ What You Get: The 5-Tab Interactive Dashboard

Trailblazer compiles your investigation into a single, dependency-free HTML dashboard with 5 specialized views:

| Tab | What It Gives You |
|---|---|
| **📖 Story** | Executive walkthrough with a 5-step progress stepper and **3 toggleable depth levels**: `Simple` (plain English), `Detailed` (technical mechanics), and `Deep` (historical architectural rationale). |
| **🗺️ Map** | Clean package architecture topology highlighting modules directly on the investigation trail vs. nearby untouched components. |
| **🔀 Flow** | Animated, step-by-step sequence diagram with **directional SVG arrowheads**, component lifelines, and explicit failure-point markers. |
| **💻 Code** | Interactive code trail with syntax highlighting, pointer annotations, one-click copy, and direct **"View on GitHub / Bitbucket"** source links to the exact lines at git `HEAD`. |
| **🛡️ Your Change** | Invariant blueprint declaring **what must remain true**, what is permitted to vary, the target file, and exact verification test commands. |

---

## 💎 Key Features & Architecture

- **Zero Runtime Dependencies**: Operates entirely with the Python 3.8+ standard library and native vanilla Web Components. No Node.js, npm, or Docker required.
- **Zero-Token Pre-filtering**: Local `git grep` searches find candidate symbols locally before any file is read into the AI context window, saving up to 97% of input tokens.
- **Strict Invariant Guardrails**: Separates what is broken from what must never be broken, preventing agents from recommending destructive "hacks".
- **Local Git Tree Verification**: The compiler (`compile.py`) cross-checks file paths and line ranges against real disk files to prevent hallucinated line citations.
- **Portable Trace Bundles**: Package an entire investigation into a portable `.tbz.zip` bundle with `--bundle` for offline archiving and peer review.
- **Session Dashboard**: Run `--dashboard` to scan your `.tbz/` history and review past investigations across the project.

---

## 🛠️ CLI Reference: `compile.py`

```text
python3 scripts/compile.py [TRACE_JSON] [OPTIONS]

Core Operations:
  --repo PATH       Cross-validate code snippets and line bounds against repository root
  --out DIR         Destination directory for compiled index.html (default: trace directory)
  --serve           Launch local web server and open browser (default: http://127.0.0.1:4200/)
  --port N          Specify starting HTTP port (default: 4200)
  --no-open         Do not auto-launch browser when starting server
  --check-only      Validate schema and repository bounds without compiling HTML

Workflows & Utilities:
  --init SLUG       Scaffold a new .tbz/<slug>/trace.json template from the CLI
  --watch           Watch trace.json for file modifications and automatically recompile
  --bundle          Package trace.json, HTML report, and manifest into shareable .tbz.zip
  --dashboard [DIR] Scan directory (default: .tbz/) and generate multi-trace history dashboard
  --prefilter QUERY Run local zero-token regex search across repository files
```

---

## 📂 Repository Layout

```text
trailblazer/
├── SKILL.md                # Agent instruction & prompt contract
├── package.json            # Skill discovery configuration
├── scripts/
│   └── compile.py          # Python stdlib validator, compiler & HTTP server
├── assets/
│   ├── template.html       # 5-tab self-contained interactive dashboard
│   └── dashboard.html      # Multi-trace session history viewer
├── mcp-server/
│   └── server.py           # Zero-dependency MCP server (6 native tools)
├── references/
│   └── trace-schema.md     # Canonical trace.json schema definition
└── examples/
    ├── example-trace.json  # Comprehensive reference investigation (Nova Engine)
    └── minimal-trace.json  # Clean, minimal 3-stop reference investigation
```

---

## 📄 License

MIT © 2026 Trailblazer Contributors
