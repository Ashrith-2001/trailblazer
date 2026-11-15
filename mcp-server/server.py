#!/usr/bin/env python3
"""
Trailblazer MCP Server - Zero-dependency Model Context Protocol server.
Allows AI coding agents to use Trailblazer without managing skill directories.
Python 3.8+ standard library only.

HOW THIS MCP WORKS
------------------
Trailblazer is an investigation documentation tool. The AI agent (Claude Code,
Cursor, etc.) IS the investigation engine — it reads code, runs shell commands,
and reasons about the codebase. The MCP tools handle the output pipeline:

  Typical flow:
    1. User asks: "Investigate why X happens in this repo"
    2. Agent reads code, runs grep/git, builds evidence autonomously
    3. Agent calls trailblazer_start  → scaffolds .tbz/<id>/trace.json template
    4. Agent fills trace.json with its findings (writes the file directly)
    5. Agent calls trailblazer_validate → checks schema + cross-checks file paths
    6. Agent calls trailblazer_compile  → renders HTML dashboard + serves it
    7. Agent tells user: "Dashboard live at http://127.0.0.1:4200/"

  For pre-investigation search (zero-token prefilter):
    - trailblazer_prefilter → grep/git-grep across repo before reading any file

  For report packaging/history:
    - trailblazer_bundle     → zip report for sharing
    - trailblazer_list_traces→ list past investigations in .tbz/

IMPORTANT: trailblazer_validate accepts a trace.json path, NOT a source file.
           Never call it on .py/.ts/.go files — only on trace.json files.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict

# Locate trailblazer compile.py
TRAILBLAZER_ROOT = Path(__file__).resolve().parent.parent
COMPILE_SCRIPT = TRAILBLAZER_ROOT / "scripts" / "compile.py"
SCHEMA_REF = TRAILBLAZER_ROOT / "references" / "trace-schema.md"
EXAMPLE_TRACE = TRAILBLAZER_ROOT / "examples" / "example-trace.json"

TOOLS = [
    {
        "name": "trailblazer_start",
        "description": (
            "Bootstrap a new Trailblazer investigation. Creates the .tbz/<issue-id>/ "
            "directory and scaffolds a trace.json template for the agent to fill in. "
            "Call this FIRST when starting any new investigation. The agent then reads "
            "code, runs grep/git commands, and writes its findings into the scaffolded "
            "trace.json — the agent generates trace.json, users never write it manually."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "issue_id": {
                    "type": "string",
                    "description": "Short slug for the investigation (e.g. 'dual-routing-review', 'jwt-stale-lock'). Used as the directory name under .tbz/"
                },
                "title": {
                    "type": "string",
                    "description": "One-sentence description of the question or bug being investigated"
                },
                "repo_path": {
                    "type": "string",
                    "description": "Absolute path to the repository being investigated (defaults to cwd)"
                },
                "category": {
                    "type": "string",
                    "description": "bug | flaky-test | feature | performance | security | refactor | docs",
                    "enum": ["bug", "flaky-test", "feature", "performance", "security", "refactor", "docs"]
                }
            },
            "required": ["issue_id", "title"]
        }
    },
    {
        "name": "trailblazer_prefilter",
        "description": (
            "Zero-token local search: run grep/git-grep across a repository to locate "
            "candidate lines, symbols, and files BEFORE reading any code into model context. "
            "Use this at the start of investigation to find where a symbol, error message, "
            "or function name appears — then read only those targeted line ranges."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Regex or symbol name (e.g. error message, function name, class identifier)"
                },
                "repo_path": {
                    "type": "string",
                    "description": "Path to the repository root (defaults to current working directory)"
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "trailblazer_validate",
        "description": (
            "Validate a trace.json investigation file against the Trailblazer schema. "
            "Call this AFTER the agent has written its findings into trace.json. "
            "IMPORTANT: trace_path must point to a trace.json file — never a source code "
            "file (.py, .ts, .go, etc.). trace.json is the structured investigation report "
            "the agent generates, not the code being investigated."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {
                    "type": "string",
                    "description": "Path to the trace.json investigation file to validate (e.g. .tbz/my-issue/trace.json)"
                },
                "repo_path": {
                    "type": "string",
                    "description": "Optional: path to the investigated repo, to cross-check that file paths and line numbers in the trace exist"
                }
            },
            "required": ["trace_path"]
        }
    },
    {
        "name": "trailblazer_compile",
        "description": (
            "Compile a validated trace.json into a self-contained interactive HTML dashboard "
            "with 5 tabs: Story, Map, Flow, Code, Your change. Optionally start a local server. "
            "Call this after trailblazer_validate passes. The dashboard is what the user sees."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {
                    "type": "string",
                    "description": "Path to the trace.json file (e.g. .tbz/my-issue/trace.json)"
                },
                "output_dir": {
                    "type": "string",
                    "description": "Optional directory to write index.html (defaults to same folder as trace.json)"
                },
                "serve": {
                    "type": "boolean",
                    "description": "Start a background HTTP server at http://127.0.0.1:4200/ after compiling"
                }
            },
            "required": ["trace_path"]
        }
    },
    {
        "name": "trailblazer_list_traces",
        "description": "List all past Trailblazer investigation traces found in the .tbz directory. Use to review previous investigations on this repository.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tbz_dir": {
                    "type": "string",
                    "description": "Path to the .tbz directory (defaults to .tbz in current working directory)"
                }
            }
        }
    },
    {
        "name": "trailblazer_bundle",
        "description": "Package an investigation trace.json and its compiled HTML report into a portable .tbz.zip file for sharing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "trace_path": {
                    "type": "string",
                    "description": "Path to the trace.json file to bundle"
                }
            },
            "required": ["trace_path"]
        }
    }
]


def handle_start(args: Dict[str, Any]) -> str:
    """Scaffold a new investigation: create .tbz/<issue-id>/trace.json template."""
    issue_id = args.get("issue_id", "").strip()
    if not issue_id:
        return "ERROR: issue_id is required (e.g. 'dual-routing-review')"

    repo_path = Path(args.get("repo_path") or os.getcwd()).resolve()
    tbz_dir = repo_path / ".tbz" / issue_id
    tbz_dir.mkdir(parents=True, exist_ok=True)

    trace_path = tbz_dir / "trace.json"
    if trace_path.exists():
        return (
            f"Investigation already exists at {trace_path}\n"
            f"Delete it first or choose a different issue_id."
        )

    title = args.get("title", "Untitled investigation")
    category = args.get("category", "bug")

    # Load example trace as structural reference
    example = {}
    if EXAMPLE_TRACE.exists():
        try:
            example = json.loads(EXAMPLE_TRACE.read_text(encoding="utf-8"))
        except Exception:
            pass

    # Scaffold a clean, canonical template the agent should fill in
    template = {
        "version": "1.0.0",
        "repository": str(repo_path),
        "issue": {
            "id": issue_id,
            "title": title,
            "url": "",
            "category": category,
            "commit": "HEAD"
        },
        "summary": {
            "problem": "TODO: one sentence — what behavior is observed vs expected",
            "rootCause": "TODO: one sentence — the precise mechanism causing failure (cite file:line)",
            "patchTarget": "TODO: one sentence — where and how the fix should be introduced"
        },
        "aiPolicy": {
            "status": "unspecified",
            "sourceFile": "",
            "summary": "Check CONTRIBUTING.md or AGENTS.md for AI contribution policy"
        },
        "evidence": {
            "level": "static-analysis",
            "confidence": 0.9,
            "commandsRun": [],
            "whatRan": "Static code analysis and git history inspection",
            "whatSkipped": "TODO: mention what tests were skipped or not run",
            "notes": "Verified by reading source code and commit history"
        },
        "trail": [
            {
                "id": "stop-1",
                "role": "entry",
                "title": "TODO: Entry point title",
                "description": "TODO: Brief note on how execution reaches here",
                "file": "TODO: relative/path/to/file.py",
                "lineStart": 1,
                "lineEnd": 10,
                "highlightLines": [5],
                "explanation": {
                    "simple": "TODO: Plain-English explanation for any engineer",
                    "detailed": "TODO: Technical mechanism explaining variables, conditionals, or calls",
                    "deep": "TODO: Architectural context, historical commits, or design tradeoffs"
                },
                "code": {
                    "lines": "TODO: Exact verbatim code snippet from file",
                    "pointer": "TODO: Pointer annotation pointing to the critical line"
                }
            },
            {
                "id": "stop-2",
                "role": "origin",
                "title": "TODO: Failure origin title",
                "description": "TODO: Where the defect originates or assumption fails",
                "file": "TODO: relative/path/to/file.py",
                "lineStart": 20,
                "lineEnd": 30,
                "highlightLines": [25],
                "explanation": {
                    "simple": "TODO: Plain-English explanation of why this goes wrong",
                    "detailed": "TODO: Technical mechanism of the error or unhandled condition",
                    "deep": "TODO: Why this code was written this way or what changed historically"
                },
                "code": {
                    "lines": "TODO: Exact verbatim code snippet from file",
                    "pointer": "TODO: Pointer annotation"
                }
            },
            {
                "id": "stop-3",
                "role": "patch",
                "title": "TODO: Patch location title",
                "description": "TODO: Exact function or block where fix should be applied",
                "file": "TODO: relative/path/to/file.py",
                "lineStart": 35,
                "lineEnd": 45,
                "highlightLines": [40],
                "explanation": {
                    "simple": "TODO: Plain-English summary of what the fix does",
                    "detailed": "TODO: Technical mechanism of the fix",
                    "deep": "TODO: Guardrails to maintain"
                },
                "code": {
                    "lines": "TODO: Verbatim code snippet where fix will be applied",
                    "pointer": "TODO: Pointer annotation"
                }
            }
        ],
        "flow": {
            "actors": ["Caller", "Service", "Storage"],
            "interactions": [
                {
                    "from": "Caller",
                    "to": "Service",
                    "action": "Invokes entry function",
                    "stopId": "stop-1",
                    "isFailurePoint": False
                },
                {
                    "from": "Service",
                    "to": "Storage",
                    "action": "Executes operation that fails or evaluates invalid state",
                    "stopId": "stop-2",
                    "isFailurePoint": True,
                    "error": "TODO: Observed error or unexpected condition"
                }
            ],
            "omittedSteps": ["Internal runtime initialization", "Logging and telemetry"]
        },
        "changeBlueprint": {
            "targetFiles": ["TODO: relative/path/to/file.py"],
            "mustKeepTrue": [
                "TODO: System invariant that must never be broken by this fix"
            ],
            "permittedToChange": [
                "TODO: Implementation details that are allowed to vary"
            ],
            "verificationCommand": "TODO: e.g. pytest tests/test_module.py",
            "suggestedTestCases": [
                "TODO: Specific edge case test to add"
            ],
            "checklist": [
                "TODO: First concrete action to take when implementing the fix"
            ]
        }
    }

    trace_path.write_text(json.dumps(template, indent=2), encoding="utf-8")

    # Add .tbz to .git/info/exclude if inside a git repo
    git_exclude = repo_path / ".git" / "info" / "exclude"
    if git_exclude.exists():
        content = git_exclude.read_text(encoding="utf-8")
        if ".tbz/" not in content:
            with git_exclude.open("a", encoding="utf-8") as f:
                f.write("\n# Trailblazer investigation data\n.tbz/\n")

    schema_hint = ""
    if SCHEMA_REF.exists():
        schema_hint = f"\nFull schema reference: {SCHEMA_REF}"

    return (
        f"✔ Investigation scaffolded at: {trace_path}\n"
        f"\nNext steps for the agent:\n"
        f"  1. Run trailblazer_prefilter to locate relevant code symbols\n"
        f"  2. Read code files and git history autonomously (grep, git log, file reads)\n"
        f"  3. Fill in trace.json with your findings (replace all TODO fields)\n"
        f"  4. Call trailblazer_validate with trace_path={trace_path}\n"
        f"  5. Call trailblazer_compile with serve=true to launch the dashboard\n"
        f"{schema_hint}"
    )


def handle_prefilter(args: Dict[str, Any]) -> str:
    query = args.get("query", "")
    repo_path = args.get("repo_path") or os.getcwd()
    cmd = [sys.executable, str(COMPILE_SCRIPT), "--repo", repo_path, "--prefilter", query]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return res.stdout or res.stderr


def handle_validate(args: Dict[str, Any]) -> str:
    trace_path_str = (args.get("trace_path") or "").strip()
    if not trace_path_str:
        return "Error: 'trace_path' is required. Provide path to your investigation trace.json (e.g. .tbz/my-issue/trace.json)."

    # Guard against passing a source code file directly
    source_exts = [".py", ".ts", ".js", ".go", ".rs", ".java", ".cpp", ".c", ".rb", ".php", ".cs"]
    if any(trace_path_str.endswith(ext) for ext in source_exts):
        return (
            f"Error: '{trace_path_str}' is a source code file, not an investigation trace.\n"
            f"trailblazer_validate checks the structured investigation document (trace.json).\n\n"
            f"Correct workflow:\n"
            f"  1. Call trailblazer_start with issue_id and title to scaffold .tbz/<id>/trace.json\n"
            f"  2. Read the source code and git history to investigate the issue\n"
            f"  3. Write your findings into the scaffolded trace.json\n"
            f"  4. Call trailblazer_validate with trace_path pointing to that trace.json"
        )

    cmd = [sys.executable, str(COMPILE_SCRIPT), trace_path_str, "--check-only"]
    if args.get("repo_path"):
        cmd.extend(["--repo", args["repo_path"]])
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return (res.stdout + "\n" + res.stderr).strip()


def handle_compile(args: Dict[str, Any]) -> str:
    trace_path = args.get("trace_path", "")
    cmd = [sys.executable, str(COMPILE_SCRIPT), trace_path]
    if args.get("output_dir"):
        cmd.extend(["--out", args["output_dir"]])
    if args.get("serve"):
        cmd.extend(["--serve", "--no-open"])
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return (res.stdout + "\n" + res.stderr).strip()


def handle_list_traces(args: Dict[str, Any]) -> str:
    tbz_dir = Path(args.get("tbz_dir") or ".tbz").resolve()
    if not tbz_dir.exists():
        return f"No .tbz directory found at: {tbz_dir}"

    traces = []
    for p in tbz_dir.glob("**/trace.json"):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            issue = data.get("issue", {})
            summary = data.get("summary", {})
            traces.append({
                "issue_id": issue.get("id", ""),
                "title": issue.get("title", ""),
                "category": issue.get("category", "bug"),
                "problem": summary.get("problem", ""),
                "path": str(p)
            })
        except Exception:
            continue
    return json.dumps(traces, indent=2)


def handle_bundle(args: Dict[str, Any]) -> str:
    trace_path = args.get("trace_path", "")
    cmd = [sys.executable, str(COMPILE_SCRIPT), trace_path, "--bundle"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    return (res.stdout + "\n" + res.stderr).strip()


def handle_tool_call(name: str, arguments: Dict[str, Any]) -> str:
    if name == "trailblazer_start":
        return handle_start(arguments)
    elif name == "trailblazer_prefilter":
        return handle_prefilter(arguments)
    elif name == "trailblazer_validate":
        return handle_validate(arguments)
    elif name == "trailblazer_compile":
        return handle_compile(arguments)
    elif name == "trailblazer_list_traces":
        return handle_list_traces(arguments)
    elif name == "trailblazer_bundle":
        return handle_bundle(arguments)
    else:
        raise ValueError(f"Unknown tool: {name}")


def send_response(req_id: Any, result: Any = None, error: Any = None):
    resp = {"jsonrpc": "2.0", "id": req_id}
    if error is not None:
        resp["error"] = error
    else:
        resp["result"] = result
    out = json.dumps(resp)
    sys.stdout.write(out + "\n")
    sys.stdout.flush()


def main():
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue

            # MCP stdio transport: plain newline-delimited JSON (one object per line)
            body = line

            if not body:
                continue

            msg = json.loads(body)
            req_id = msg.get("id")
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "initialize":
                send_response(req_id, {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {
                        "tools": {}
                    },
                    "serverInfo": {
                        "name": "trailblazer-mcp",
                        "version": "1.0.0"
                    }
                })
            elif method == "notifications/initialized":
                pass
            elif method == "ping":
                send_response(req_id, {})
            elif method == "tools/list":
                send_response(req_id, {"tools": TOOLS})
            elif method == "tools/call":
                t_name = params.get("name")
                t_args = params.get("arguments", {})
                try:
                    text_res = handle_tool_call(t_name, t_args)
                    send_response(req_id, {
                        "content": [{"type": "text", "text": text_res}]
                    })
                except Exception as exc:
                    send_response(req_id, {
                        "content": [{"type": "text", "text": f"Error: {exc}"}],
                        "isError": True
                    })
            else:
                if req_id is not None:
                    send_response(req_id, error={"code": -32601, "message": f"Method {method} not found"})
        except Exception as e:
            sys.stderr.write(f"MCP Server error: {e}\n")
            sys.stderr.flush()


if __name__ == "__main__":
    main()
