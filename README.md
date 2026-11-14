# 🧭 Trailblazer

**Follow the trail from an issue to its root cause.**

Trailblazer is a verified codebase investigation tool and coding agent engine. When assigned an issue in an unfamiliar or massive repository, Trailblazer traces only the relevant code path, validates findings directly against the repository's git tree, and compiles a clean, interactive local dashboard on `http://localhost:4200`.

---

## ✨ Why Trailblazer?

- **Zero-Token Hallucination Protection**: Every code snippet and claim is cross-validated by a strict local Python checker (`compile.py`) against real lines in the repository.
- **Zero-Dependency Runtime**: No Node.js, npm, or heavy framework required on the user's machine. Operates entirely with the Python 3.8+ standard library and modern, responsive web components.
- **Token-Optimized Architecture**: Designed with local pre-filtering to save up to 70% of LLM token expenditure compared to traditional agent searches.
- **AI Policy Radar**: Automatically detects and surfaces repository contribution policies regarding AI tools.
- **Clean Invariant Guardrails**: Clear separation of *what must remain true* versus *what is permitted to change*.
- **Interactive Sequence Flow**: Step-by-step actor interactions with directional arrows, animated execution, and failure point highlighting.
- **Multiple Integration Modes**: Use as a standard agent skill, an MCP server, or standalone CLI tool.

---

## 🚀 Ways to Use Trailblazer

### Mode A: MCP Server (Recommended — No Skill Directories Needed!)
Skip copying folders into multiple agent directories. Register Trailblazer as an MCP (Model Context Protocol) server in your agent settings (Cursor, Claude Desktop, Antigravity, VS Code, etc.):

```json
{
  "mcpServers": {
    "trailblazer": {
      "command": "python3",
      "args": ["/path/to/trailblazer/mcp-server/server.py"]
    }
  }
}
```

The agent automatically gets access to 5 native tools:
- `trailblazer_prefilter`: Zero-token local symbol/regex search
- `trailblazer_validate`: Validates `trace.json` schema and invariants
- `trailblazer_compile`: Compiles `trace.json` into the interactive HTML dashboard
- `trailblazer_list_traces`: Lists all investigation sessions for the project
- `trailblazer_bundle`: Packages trace and report into a portable `.tbz.zip`

---

### Mode B: Agent Skill
Install Trailblazer into your agent's skills directory:
```bash
git clone https://github.com/Ashrith-2001/trailblazer ~/.agents/skills/trailblazer
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

### Mode C: Standalone CLI Demo
You can test the compiler and preview the interactive dashboard immediately:
```bash
python3 scripts/compile.py examples/example-trace.json --serve
```

---

## 📂 Repository Structure

```
trailblazer/
├── SKILL.md                # Agent instruction & prompt contract
├── package.json            # Skill discovery and CLI configuration
├── scripts/
│   └── compile.py          # Python standard library validator & compiler
├── assets/
│   ├── template.html       # Self-contained, responsive dashboard
│   └── dashboard.html      # Multi-trace session history dashboard
├── mcp-server/
│   └── server.py           # Zero-dependency Python MCP server
├── references/
│   └── trace-schema.md     # trace.json schema definition
└── examples/
    └── example-trace.json  # Comprehensive reference example
```

---

## 🛠️ CLI Options for `compile.py`

```text
python3 scripts/compile.py [TRACE_JSON] [OPTIONS]

Core Options:
  --repo PATH       Cross-validate code snippets and line numbers against a local repository clone
  --out DIR         Custom destination directory for generated index.html
  --serve           Start local HTTP server and open browser (default port 4200)
  --port N          Specify starting port (default: 4200)
  --no-open         Do not auto-launch system browser
  --check-only      Validate trace.json without rendering HTML output

Enhancements:
  --bundle          Package trace and HTML report into a shareable .tbz.zip archive
  --dashboard [DIR] Scan directory (default: .tbz) and compile a multi-trace session dashboard
  --prefilter QUERY Run zero-token regex search across repository files
```

---

## 📄 License
MIT © 2026 Trailblazer Contributors
