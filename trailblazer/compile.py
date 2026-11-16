#!/usr/bin/env python3
"""
Trailblazer compile.py - Validator, Compiler & Local Server for Trailblazer Traces
Zero-dependency CLI tool (Python 3.8+ standard library only).
"""

import argparse
import html
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
DEFAULT_PORT = 4200
TRAILBLAZER_ROOT = Path(__file__).resolve().parent.parent

if str(TRAILBLAZER_ROOT) not in sys.path:
    sys.path.insert(0, str(TRAILBLAZER_ROOT))

# Color and formatting helpers
USE_COLOR = sys.stdout.isatty() and os.name != "nt"


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


def bold(text: str) -> str:
    return c(text, "1")


def green(text: str) -> str:
    return c(text, "32")


def yellow(text: str) -> str:
    return c(text, "33")


def red(text: str) -> str:
    return c(text, "31")


def cyan(text: str) -> str:
    return c(text, "36")


class ValidationError(Exception):
    pass


def normalize_trace_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes common field aliases into the canonical trace schema.
    Ensures seamless compatibility across different agent prompts and skill definitions.
    """
    if not isinstance(data, dict):
        return data

    # 1. Top-level repository
    if not data.get("repository"):
        data["repository"] = data.get("repo") or "local/repo"

    # 2. Version
    if not data.get("version"):
        data["version"] = SCHEMA_VERSION

    # 3. Summary aliases
    summary = data.get("summary")
    if isinstance(summary, dict):
        if "rootCause" not in summary and "cause" in summary:
            summary["rootCause"] = summary["cause"]
        if "patchTarget" not in summary and "fix" in summary:
            summary["patchTarget"] = summary["fix"]

    # 4. Change blueprint aliases (yourChange -> changeBlueprint)
    if "changeBlueprint" not in data and "yourChange" in data:
        yc = data["yourChange"]
        if isinstance(yc, dict):
            target_files = yc.get("needsChange") or []
            cleaned_targets = []
            for t in target_files:
                cleaned_targets.append(t.split(":")[0].strip() if isinstance(t, str) else str(t))

            data["changeBlueprint"] = {
                "targetFiles": cleaned_targets,
                "mustKeepTrue": (yc.get("keepChecking") or []) + (yc.get("mustNotBreak") or []),
                "permittedToChange": yc.get("allowToVary") or [],
                "verificationCommand": yc.get("testToExtend") or yc.get("verificationCommand") or "",
                "suggestedTestCases": [],
                "checklist": [yc.get("firstThing")] if yc.get("firstThing") else [],
                "noChange": yc.get("noChange") or []
            }

    # 5. Trail stops normalization
    trail = data.get("trail")
    if isinstance(trail, list):
        for idx, stop in enumerate(trail):
            if not isinstance(stop, dict):
                continue
            if not stop.get("id"):
                stop["id"] = f"stop-{idx + 1}"
            if "role" not in stop and "stop" in stop:
                stop["role"] = stop["stop"]
            if "title" not in stop and "label" in stop:
                stop["title"] = stop["label"]
            if "explanation" not in stop and "explain" in stop:
                stop["explanation"] = stop["explain"]
            if "code" not in stop:
                snippet = stop.get("snippet", "")
                pointer = stop.get("pointer", "")
                stop["code"] = {"lines": snippet, "pointer": pointer}

    # 6. Flow interactions normalization (steps -> interactions)
    flow = data.get("flow")
    if isinstance(flow, dict):
        if "interactions" not in flow and "steps" in flow:
            steps = flow.get("steps") or []
            interactions = []
            for s in steps:
                if isinstance(s, dict):
                    interactions.append({
                        "from": s.get("from", "Caller"),
                        "to": s.get("to", "Component"),
                        "action": s.get("label") or s.get("action", "action"),
                        "isFailurePoint": s.get("stepType") == "failure" or s.get("isFailurePoint", False),
                        "error": s.get("error", "")
                    })
            flow["interactions"] = interactions

    # 7. Verification block normalization
    ver = data.get("verification")
    if isinstance(ver, dict):
        if "confidenceScore" not in ver and "confidence" in ver:
            c = ver["confidence"]
            ver["confidenceScore"] = int(c * 100) if c <= 1.0 else int(c)
        if "status" not in ver:
            score = ver.get("confidenceScore", 90)
            ver["status"] = "verified" if score >= 80 else "speculative"

    return data


class TraceValidator:
    """Validates trace.json data integrity, bounds, invariants and repo alignment."""

    def __init__(self, data: Dict[str, Any], repo_path: Optional[Path] = None):
        self.data = normalize_trace_data(data)
        self.repo = repo_path.resolve() if repo_path and repo_path.exists() else None
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def log_error(self, msg: str):
        self.errors.append(msg)

    def log_warning(self, msg: str):
        self.warnings.append(msg)

    def validate(self) -> Tuple[List[str], List[str]]:
        self._check_top_level()
        self._check_issue()
        self._check_summary()
        self._check_evidence()
        self._check_trail()
        self._check_flow()
        self._check_change_blueprint()
        self._check_metrics()
        self._check_verification()

        if self.repo:
            self._verify_against_repo()

        return self.errors, self.warnings

    def _check_verification(self):
        ver = self.data.get("verification")
        if not ver:
            return
        if not isinstance(ver, dict):
            self.log_warning("'verification' should be an object containing dialectic audit results")
            return
        score = ver.get("confidenceScore")
        if score is not None and (not isinstance(score, (int, float)) or not (0 <= score <= 100)):
            self.log_warning("'verification.confidenceScore' should be a numeric score between 0 and 100")

    def _check_top_level(self):
        req = ["repository", "issue", "summary", "evidence", "trail", "changeBlueprint"]
        for f in req:
            if f not in self.data:
                self.log_error(f"Missing required top-level property: '{f}'")

    def _check_issue(self):
        issue = self.data.get("issue")
        if not isinstance(issue, dict):
            self.log_error("'issue' must be an object")
            return
        if not issue.get("id"):
            self.log_error("'issue.id' is required")
        if not issue.get("title"):
            self.log_error("'issue.title' is required")

        valid_cats = ["bug", "flaky-test", "feature", "performance", "security", "refactor", "docs"]
        cat = issue.get("category")
        if cat and cat not in valid_cats:
            self.log_warning(f"'issue.category' '{cat}' is unusual; standard categories: {', '.join(valid_cats)}")

    def _check_summary(self):
        summary = self.data.get("summary")
        if not isinstance(summary, dict):
            self.log_error("'summary' must be an object")
            return
        for field in ["problem", "rootCause", "patchTarget"]:
            val = summary.get(field)
            if not val or not isinstance(val, str) or not val.strip():
                self.log_error(f"'summary.{field}' is required and must be non-empty")
            elif len(val.split()) > 40:
                self.log_warning(f"'summary.{field}' is verbose ({len(val.split())} words; recommend <= 25 words)")

    def _check_evidence(self):
        ev = self.data.get("evidence")
        if not isinstance(ev, dict):
            self.log_error("'evidence' must be an object")
            return

        valid_levels = ["reproduced-real", "reproduced-isolated", "static-analysis", "inferred"]
        level = ev.get("level")
        if not level or level not in valid_levels:
            self.log_error(f"'evidence.level' must be one of: {', '.join(valid_levels)}")

        conf = ev.get("confidence")
        if conf is not None:
            if not isinstance(conf, (int, float)) or not (0.0 <= conf <= 1.0):
                self.log_error("'evidence.confidence' must be a float between 0.0 and 1.0")

        if level == "reproduced-real" and not ev.get("commandsRun"):
            self.log_error("'evidence.level' is 'reproduced-real' but no commandsRun listed")

        if level != "reproduced-real" and not ev.get("whatSkipped"):
            self.log_warning("Evidence level is not 'reproduced-real', but 'whatSkipped' explanation was omitted")

    def _check_trail(self):
        trail = self.data.get("trail")
        if not isinstance(trail, list) or len(trail) < 2:
            self.log_error("'trail' must be a list containing at least 2 stops")
            return
        if len(trail) > 8:
            self.log_warning(f"'trail' has {len(trail)} stops; recommend 3 to 6 focused stops for clarity")

        valid_roles = ["entry", "transit", "origin", "patch"]
        seen_roles = set()
        for idx, stop in enumerate(trail):
            if not isinstance(stop, dict):
                self.log_error(f"trail stop [{idx}] must be an object")
                continue
            role = stop.get("role")
            if not role or role not in valid_roles:
                self.log_error(f"trail stop [{idx}] invalid role: '{role}'. Must be: {', '.join(valid_roles)}")
            else:
                seen_roles.add(role)

            for req in ["id", "title", "file"]:
                if not stop.get(req):
                    self.log_error(f"trail stop [{idx}] missing '{req}'")

            start = stop.get("lineStart")
            end = stop.get("lineEnd")
            if start is not None and end is not None:
                if not isinstance(start, int) or not isinstance(end, int) or start > end:
                    self.log_error(f"trail stop [{idx}] lineStart ({start}) cannot exceed lineEnd ({end})")

        if "origin" not in seen_roles and "patch" not in seen_roles:
            self.log_warning("Trail does not explicitly tag an 'origin' or 'patch' stop")

    def _check_flow(self):
        flow = self.data.get("flow")
        if not flow or not isinstance(flow, dict):
            return

        actors = set(flow.get("actors", []))
        for idx, step in enumerate(flow.get("interactions", [])):
            frm = step.get("from")
            to = step.get("to")
            if frm and frm not in actors:
                self.log_warning(f"flow interaction [{idx}] 'from' actor '{frm}' not listed in actors list")
            if to and to not in actors:
                self.log_warning(f"flow interaction [{idx}] 'to' actor '{to}' not listed in actors list")

    def _check_change_blueprint(self):
        bp = self.data.get("changeBlueprint")
        if not isinstance(bp, dict):
            self.log_error("'changeBlueprint' must be an object")
            return

        if bp.get("permittedToChange") and not bp.get("mustKeepTrue"):
            self.log_error(
                "'changeBlueprint.permittedToChange' requires 'mustKeepTrue' invariants to be specified"
            )

    def _check_metrics(self):
        metrics = self.data.get("metrics")
        if not metrics or not isinstance(metrics, list):
            return
        for idx, m in enumerate(metrics):
            if not m.get("label") or not m.get("value"):
                self.log_error(f"metrics [{idx}] requires 'label' and 'value'")
            if not m.get("explanation"):
                self.log_warning(f"metrics [{idx}] ({m.get('label')}) is missing an 'explanation' string")

    def _verify_against_repo(self):
        """Verifies snippets and file paths exist directly in the local repository clone."""
        if not self.repo:
            return

        trail = self.data.get("trail", [])
        for stop in trail:
            file_rel = stop.get("file")
            if not file_rel:
                continue
            target_path = self.repo / file_rel
            if not target_path.exists():
                self.log_error(f"Repo check: File not found in repository: {file_rel}")
                continue

            # Read file and verify lines if start/end lines given
            start = stop.get("lineStart")
            end = stop.get("lineEnd")
            code_obj = stop.get("code")

            try:
                content = target_path.read_text(encoding="utf-8", errors="replace")
                lines = content.splitlines()

                if start and end:
                    if start < 1 or end > len(lines):
                        self.log_error(
                            f"Repo check: Line range {start}-{end} outside file bounds ({len(lines)} lines) in {file_rel}"
                        )
                    elif code_obj and "lines" in code_obj:
                        expected = code_obj["lines"].strip()
                        actual = "\n".join(lines[start - 1 : end]).strip()
                        # Normalize whitespace for comparison
                        norm_exp = re.sub(r"\s+", " ", expected)
                        norm_act = re.sub(r"\s+", " ", actual)
                        if norm_exp not in norm_act and norm_act not in norm_exp:
                            self.log_warning(
                                f"Repo check: Code snippet for stop '{stop.get('id')}' in {file_rel} differs from lines {start}-{end} on disk"
                            )
            except Exception as e:
                self.log_warning(f"Repo check: Could not read {file_rel}: {e}")

        # Static AST Grounding & Dialectic Verification
        try:
            from scripts.ast_engine import build_codebase_index
            idx = build_codebase_index(self.repo)
            ast_res = idx.verify_trace(self.data)

            for issue in ast_res.get("issues", []):
                if issue.get("severity") == "warning":
                    self.log_warning(f"AST Grounding: {issue.get('message')}")

            if "verification" not in self.data or not isinstance(self.data["verification"], dict):
                self.data["verification"] = {}
            ver = self.data["verification"]
            ver["astGrounding"] = {
                "score": ast_res["grounding_score"],
                "verifiedStops": ast_res["verified_stops"],
                "totalStops": ast_res["total_stops"],
                "verifiedEdges": ast_res["verified_edges"],
                "possibleEdges": ast_res["possible_edges"]
            }
            if "confidenceScore" not in ver:
                ev = self.data.get("evidence", {})
                ev_level = ev.get("level", "static-analysis")
                ev_weight = 1.0 if ev_level == "reproduced-real" else (0.85 if ev_level == "reproduced-isolated" else 0.7)
                ver["confidenceScore"] = round((ast_res["grounding_score"] * 0.6 + ev_weight * 100 * 0.4), 1)
                ver["status"] = "verified" if ver["confidenceScore"] >= 75 else "speculative"
                if "judgeVerdict" not in ver:
                    ver["judgeVerdict"] = f"AST symbol analysis verified {ast_res['verified_stops']}/{ast_res['total_stops']} stops with {ast_res['grounding_score']}% grounding."
        except Exception:
            pass


class TraceCompiler:
    """Injects sanitized trace data into the single-file template and writes the output HTML."""

    def __init__(self, trace_path: Path, template_path: Path, output_dir: Optional[Path] = None):
        self.trace_path = trace_path.resolve()
        self.template_path = template_path.resolve()
        self.output_dir = output_dir.resolve() if output_dir else self.trace_path.parent

    def compile(self, data: Dict[str, Any]) -> Path:
        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found at: {self.template_path}")

        data = normalize_trace_data(data)
        template_content = self.template_path.read_text(encoding="utf-8")

        # Encode JSON safely, escaping script tags to prevent XSS injection
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        safe_json = json_str.replace("</", "<\\/")

        # Replace data payload placeholder
        placeholder_token = "/*__TRAILBLAZER_DATA__*/"
        if placeholder_token in template_content:
            rendered = template_content.replace(placeholder_token, safe_json)
        elif "__TRAILBLAZER_DATA__" in template_content:
            rendered = template_content.replace("__TRAILBLAZER_DATA__", safe_json)
        else:
            # Fallback insertion before closing body
            inject = f'<script id="trailblazer-data" type="application/json">\n{safe_json}\n</script>'
            rendered = template_content.replace("</body>", f"{inject}\n</body>")

        self.output_dir.mkdir(parents=True, exist_ok=True)
        out_file = self.output_dir / "index.html"
        out_file.write_text(rendered, encoding="utf-8")
        return out_file


def resolve_asset(name: str) -> Path:
    """Finds an asset file whether running from a local checkout or installed package."""
    pkg_assets = Path(__file__).resolve().parent / "assets" / name
    if pkg_assets.exists():
        return pkg_assets
    repo_assets = Path(__file__).resolve().parent.parent / "assets" / name
    if repo_assets.exists():
        return repo_assets
    return pkg_assets

def create_trace_bundle(trace_path: Path, html_path: Path, out_zip: Optional[Path] = None) -> Path:
    """Exports self-contained .tbz.zip bundle containing HTML, trace.json, and metadata."""
    if not out_zip:
        out_zip = trace_path.parent / f"{trace_path.parent.name or 'trace'}.tbz.zip"

    with zipfile.ZipFile(out_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(html_path, arcname="index.html")
        zf.write(trace_path, arcname="trace.json")
        manifest = {
            "generator": "Trailblazer",
            "version": SCHEMA_VERSION,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "source_trace": trace_path.name
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))

    return out_zip


def scan_and_build_dashboard(scan_dir: Path, template_path: Path, out_file: Optional[Path] = None) -> Path:
    """Scans scan_dir recursively for all trace.json files and compiles a sessions dashboard."""
    traces_meta = []

    for trace_file in scan_dir.glob("**/trace.json"):
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
            issue = data.get("issue", {})
            summary = data.get("summary", {})
            ev = data.get("evidence", {})
            trail = data.get("trail", [])

            html_candidate = trace_file.parent / "index.html"
            report_path = str(html_candidate.resolve()) if html_candidate.exists() else "#"

            traces_meta.append({
                "issueId": issue.get("id", ""),
                "title": issue.get("title", trace_file.parent.name),
                "category": issue.get("category", "bug"),
                "problem": summary.get("problem", ""),
                "rootCause": summary.get("rootCause", ""),
                "evidenceLevel": ev.get("level", "inferred"),
                "confidence": ev.get("confidence", 0.9),
                "stopCount": len(trail),
                "reportPath": report_path
            })
        except Exception as e:
            continue

    if not out_file:
        out_file = scan_dir / "dashboard.html"

    template_content = template_path.read_text(encoding="utf-8")
    payload = json.dumps(traces_meta, indent=2, ensure_ascii=False)
    rendered = template_content.replace("/*__DASHBOARD_DATA__*/", payload)
    out_file.write_text(rendered, encoding="utf-8")
    return out_file


def run_prefilter_search(repo_path: Path, query: str) -> List[Dict[str, Any]]:
    """Runs zero-token local regex/grep search on repo clone to isolate candidate functions."""
    results = []
    try:
        cmd = ["git", "-C", str(repo_path), "grep", "-n", "-I", "-E", "-e", query]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
        lines = proc.stdout.splitlines()[:25]  # Limit to 25 hits to protect context
        for l in lines:
            parts = l.split(":", 2)
            if len(parts) >= 3:
                results.append({
                    "file": parts[0],
                    "line": int(parts[1]) if parts[1].isdigit() else 0,
                    "content": parts[2].strip()
                })
    except Exception as e:
        pass
    return results


def find_free_port(start_port: int, max_attempts: int = 50) -> int:
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start_port


def serve_directory(serve_dir: Path, port: int, auto_open: bool = True):
    """Starts local HTTP server for the compiled report."""
    os.chdir(str(serve_dir))

    class QuietHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            # Suppress normal access logs to keep terminal quiet
            pass

    server = TCPServer(("127.0.0.1", port), QuietHandler)
    url = f"http://127.0.0.1:{port}/"

    banner_w = 60
    print("\n" + cyan("┌" + "─" * banner_w + "┐"))
    print(cyan("│") + bold(green("  🧭 Trailblazer Investigation Dashboard".ljust(banner_w))) + cyan("│"))
    print(cyan("│") + f"  → {bold(url)}".ljust(banner_w + (len(bold(url)) - len(url))) + cyan("│"))
    print(cyan("│") + "  Press Ctrl+C to stop the server".ljust(banner_w) + cyan("│"))
    print(cyan("└" + "─" * banner_w + "┘\n"))

    if auto_open:
        threading.Thread(target=lambda: (time.sleep(0.3), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Trailblazer server.")
        server.server_close()


def main():
    parser = argparse.ArgumentParser(
        description="Trailblazer CLI: Validate, compile, and serve issue investigation reports."
    )
    parser.add_argument("trace_json", type=str, nargs="?", default=None, help="Path to trace.json file")
    parser.add_argument(
        "--repo",
        type=str,
        default=None,
        help="Path to repository root clone to cross-validate snippets and paths",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Output directory to write compiled index.html (default: same folder as trace.json)",
    )
    parser.add_argument(
        "--template",
        type=str,
        default=None,
        help="Path to custom template.html (default: assets/template.html relative to this script)",
    )
    parser.add_argument("--check-only", action="store_true", help="Perform validation only; do not compile HTML")
    parser.add_argument("--serve", action="store_true", help="Launch background/local server and open in browser")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Starting port for server (default {DEFAULT_PORT})")
    parser.add_argument("--no-open", action="store_true", help="Do not automatically open browser when serving")
    parser.add_argument("--bundle", action="store_true", help="Package trace and report into shareable .tbz.zip archive")
    parser.add_argument("--dashboard", type=str, nargs="?", const=".tbz", default=None, help="Scan directory (default .tbz) and build sessions dashboard")
    parser.add_argument("--prefilter", type=str, default=None, help="Run zero-token regex search on repository clone")
    parser.add_argument("--init", type=str, default=None, metavar="SLUG", help="Scaffold a new .tbz/<slug>/trace.json template")
    parser.add_argument("--watch", action="store_true", help="Watch trace.json for file modifications and automatically recompile")
    parser.add_argument(
        "--install-claude",
        action="store_true",
        help="Register /trailblazer slash command in Claude Code (~/.claude/commands)",
    )

    args = parser.parse_args()
    script_dir = Path(__file__).resolve().parent

    # Install Claude Code Slash Command Mode
    if args.install_claude:
        claude_dir = Path.home() / ".claude"
        commands_dir = claude_dir / "commands"
        skills_dir = claude_dir / "skills"
        commands_dir.mkdir(parents=True, exist_ok=True)
        skills_dir.mkdir(parents=True, exist_ok=True)

        cmd_file = commands_dir / "trailblazer.md"
        cmd_content = (
            "---\n"
            "description: Follow the trail from an issue to its root cause. Explains an assigned issue as an interactive, 5-tab localhost dashboard (Story, Codebase Map, Flow, Code, Your change). (user)\n"
            "---\n\n"
            "Investigate the following issue using Trailblazer:\n"
            "$ARGUMENTS\n\n"
            "Investigation instructions:\n"
            "1. Call `trailblazer_start` with a short issue slug and the question/issue as title.\n"
            "2. Use `trailblazer_prefilter` to locate candidate symbols locally before reading files.\n"
            "3. Read only targeted line ranges around relevant functions.\n"
            "4. Construct the 3 to 6 stop causal trail from entry point to origin to patch target.\n"
            "5. Fill in `.tbz/<issue-id>/trace.json` with your verified findings.\n"
            "6. Run `trailblazer_validate` and compile with `serve=true`.\n"
            "7. Present a concise summary with the problem, root cause, patch target, and the dashboard link at http://127.0.0.1:4200/.\n"
        )
        cmd_file.write_text(cmd_content, encoding="utf-8")

        # Link skill directory
        repo_root = script_dir.parent
        skill_target = skills_dir / "trailblazer"
        if (repo_root / "SKILL.md").exists():
            try:
                if skill_target.is_symlink() or skill_target.exists():
                    skill_target.unlink()
                skill_target.symlink_to(repo_root)
            except Exception:
                pass

        print(f"\n{green('✔ Installed /trailblazer slash command in Claude Code:')} {bold(str(cmd_file))}")
        print(f"Open Claude Code in any project and type: {cyan('/trailblazer')}\n")
        sys.exit(0)

    # Init Mode
    if args.init:
        slug = args.init.strip()
        repo_target = Path(args.repo).resolve() if args.repo else Path.cwd()
        tbz_path = repo_target / ".tbz" / slug
        tbz_path.mkdir(parents=True, exist_ok=True)
        target_trace = tbz_path / "trace.json"
        if target_trace.exists():
            print(f"{yellow('Warning:')} Investigation already exists at: {target_trace}")
            sys.exit(0)

        min_example = script_dir.parent / "examples" / "minimal-trace.json"
        if min_example.exists():
            template_data = json.loads(min_example.read_text(encoding="utf-8"))
            template_data["repository"] = str(repo_target)
            template_data["issue"]["id"] = slug
            template_data["issue"]["title"] = f"Investigation: {slug}"
            target_trace.write_text(json.dumps(template_data, indent=2), encoding="utf-8")
        else:
            target_trace.write_text("{}", encoding="utf-8")

        git_exclude = repo_target / ".git" / "info" / "exclude"
        if git_exclude.exists():
            content = git_exclude.read_text(encoding="utf-8")
            if ".tbz/" not in content:
                with git_exclude.open("a", encoding="utf-8") as f:
                    f.write("\n# Trailblazer investigation data\n.tbz/\n")

        print(f"\n{green('✔ Initialized new Trailblazer investigation:')} {bold(str(target_trace))}")
        print(f"Edit the trace file with findings, then compile:\n  {cyan(f'python3 scripts/compile.py {target_trace} --serve')}\n")
        sys.exit(0)

    # Prefilter Mode
    if args.prefilter:
        repo_target = Path(args.repo).resolve() if args.repo else Path.cwd()
        hits = run_prefilter_search(repo_target, args.prefilter)
        print(f"\n{bold(cyan(f'🔍 Zero-token search results for: \"{args.prefilter}\" in {repo_target}'))}")
        for h in hits:
            print(f"  {green(h['file'])}:{yellow(str(h['line']))}  {h['content']}")
        print(f"\nTotal matches: {len(hits)}")
        sys.exit(0)

    # Dashboard Mode
    if args.dashboard:
        dash_scan = Path(args.dashboard).resolve()
        dash_template = resolve_asset("dashboard.html")
        dash_out = dash_scan / "dashboard.html"
        built_dash = scan_and_build_dashboard(dash_scan, dash_template, dash_out)
        print(f"\n{green('✔ Compiled session dashboard:')} {bold(str(built_dash))}")
        if args.serve:
            port = find_free_port(args.port)
            serve_directory(dash_scan, port=port, auto_open=not args.no_open)
        sys.exit(0)

    if not args.trace_json:
        parser.print_help()
        sys.exit(2)

    trace_path = Path(args.trace_json).resolve()
    if not trace_path.exists():
        print(f"{red('Error:')} Trace file not found: {trace_path}", file=sys.stderr)
        sys.exit(2)

    try:
        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        print(f"{red('Error:')} Invalid JSON in {trace_path}: {err}", file=sys.stderr)
        sys.exit(2)

    repo_path = Path(args.repo).resolve() if args.repo else None
    validator = TraceValidator(trace_data, repo_path=repo_path)
    errors, warnings = validator.validate()

    # Print validation report
    if warnings:
        print(f"\n{bold(yellow(f'⚠️  {len(warnings)} Warning(s):'))}")
        for w in warnings:
            print(f"  {yellow('•')} {w}")

    def format_hint(err: str) -> Optional[str]:
        if "Missing required top-level property" in err:
            return "Ensure all required top-level keys ('repository', 'issue', 'summary', 'evidence', 'trail', 'changeBlueprint') are defined."
        if "invalid role" in err:
            return "Allowed trail stop roles are: 'entry', 'transit', 'origin', 'patch'."
        if "must be an object" in err:
            return "Verify this property is a valid JSON object/dictionary, not a string or array."
        if "Repo check: File not found" in err:
            return "File paths must be relative to the repository root clone (e.g. 'src/module/file.py')."
        if "Line range" in err:
            return "Cross-check line numbers with actual lines on disk or run git grep."
        if "reproduced-real" in err and "commandsRun" in err:
            return "Either list commandsRun: ['pytest ...'] or change evidence.level to 'static-analysis'."
        return None

    if errors:
        print(f"\n{bold(red(f'❌ {len(errors)} Validation Error(s):'))}")
        for e in errors:
            print(f"  {red('•')} {e}")
            hint = format_hint(e)
            if hint:
                print(f"    {cyan('Tip:')} {hint}")
        print(f"\n{red('Validation failed. Please correct trace.json and re-run.')}")
        sys.exit(1)

    print(f"\n{green('✔ Validation passed successfully.')}")

    ver = trace_data.get("verification")
    if ver and isinstance(ver, dict):
        score = ver.get("confidenceScore")
        status = ver.get("status", "verified")
        if score is not None:
            status_color = green if score >= 85 else (yellow if score >= 70 else red)
            print(f"  {status_color('⚖️  Verification Confidence:')} {bold(str(score))}% [{status.upper()}]")
        ast_g = ver.get("astGrounding")
        if ast_g and isinstance(ast_g, dict):
            print(f"  {cyan('🔍 AST Grounding Score:')} {bold(str(ast_g.get('score')))}% ({ast_g.get('verifiedStops')}/{ast_g.get('totalStops')} stops grounded)")

    if args.check_only:
        sys.exit(0)

    # Determine template path
    if args.template:
        template_path = Path(args.template).resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        template_path = resolve_asset("template.html")

    out_dir = Path(args.out).resolve() if args.out else trace_path.parent
    compiler = TraceCompiler(trace_path, template_path, output_dir=out_dir)

    try:
        html_out = compiler.compile(trace_data)
        print(f"{green('✔ Compiled visualization report:')} {bold(str(html_out))}")
        if args.bundle:
            bundle_out = create_trace_bundle(trace_path, html_out)
            print(f"{green('✔ Created shareable bundle archive:')} {bold(str(bundle_out))}")
    except Exception as exc:
        print(f"{red('Compilation error:')} {exc}", file=sys.stderr)
        sys.exit(2)

    if args.watch:
        def _watch_loop():
            last_mtime = trace_path.stat().st_mtime
            while True:
                time.sleep(1.0)
                try:
                    cur = trace_path.stat().st_mtime
                    if cur > last_mtime:
                        last_mtime = cur
                        print(f"\n{cyan('↻ Change detected in')} {trace_path.name}{cyan(', recompiling...')}")
                        data = json.loads(trace_path.read_text(encoding="utf-8"))
                        compiler.compile(data)
                        print(f"{green('✔ Recompiled successfully at')} {time.strftime('%H:%M:%S')}")
                except Exception as ex:
                    print(f"{yellow('Watch notice:')} {ex}")
        t = threading.Thread(target=_watch_loop, daemon=True)
        t.start()
        print(f"{cyan('👀 Watching')} {trace_path.name} {cyan('for changes...')}")

    if args.serve:
        port = find_free_port(args.port)
        serve_directory(out_dir, port=port, auto_open=not args.no_open)


if __name__ == "__main__":
    main()
