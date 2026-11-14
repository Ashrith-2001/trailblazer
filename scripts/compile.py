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
from http.server import SimpleHTTPRequestHandler
from pathlib import Path
from socketserver import TCPServer
from typing import Any, Dict, List, Optional, Tuple

SCHEMA_VERSION = "1.0.0"
DEFAULT_PORT = 4200

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


class TraceValidator:
    """Validates trace.json data integrity, bounds, invariants and repo alignment."""

    def __init__(self, data: Dict[str, Any], repo_path: Optional[Path] = None):
        self.data = data
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

        if self.repo:
            self._verify_against_repo()

        return self.errors, self.warnings

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


class TraceCompiler:
    """Injects sanitized trace data into the single-file template and writes the output HTML."""

    def __init__(self, trace_path: Path, template_path: Path, output_dir: Optional[Path] = None):
        self.trace_path = trace_path.resolve()
        self.template_path = template_path.resolve()
        self.output_dir = output_dir.resolve() if output_dir else self.trace_path.parent

    def compile(self, data: Dict[str, Any]) -> Path:
        if not self.template_path.exists():
            raise FileNotFoundError(f"Template not found at: {self.template_path}")

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

    print(f"\n{bold(green('⚡ Trailblazer server running at:'))} {bold(cyan(url))}")
    print(f"{yellow('Press Ctrl+C to stop the server.')}\n")

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
    parser.add_argument("trace_json", type=str, help="Path to trace.json file")
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

    args = parser.parse_args()

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

    if errors:
        print(f"\n{bold(red(f'❌ {len(errors)} Validation Error(s):'))}")
        for e in errors:
            print(f"  {red('•')} {e}")
        print(f"\n{red('Validation failed. Please correct trace.json and re-run.')}")
        sys.exit(1)

    print(f"\n{green('✔ Validation passed successfully.')}")

    if args.check_only:
        sys.exit(0)

    # Determine template path
    if args.template:
        template_path = Path(args.template).resolve()
    else:
        script_dir = Path(__file__).resolve().parent
        template_path = script_dir.parent / "assets" / "template.html"

    out_dir = Path(args.out).resolve() if args.out else trace_path.parent
    compiler = TraceCompiler(trace_path, template_path, output_dir=out_dir)

    try:
        html_out = compiler.compile(trace_data)
        print(f"{green('✔ Compiled visualization report:')} {bold(str(html_out))}")
    except Exception as exc:
        print(f"{red('Compilation error:')} {exc}", file=sys.stderr)
        sys.exit(2)

    if args.serve:
        port = find_free_port(args.port)
        serve_directory(out_dir, port=port, auto_open=not args.no_open)


if __name__ == "__main__":
    main()
