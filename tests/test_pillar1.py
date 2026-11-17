#!/usr/bin/env python3
"""
Unit and integration tests for Pillar 1 (AST Grounding & Dialectic Verification).
Uses Python standard library unittest only (zero external test dependencies).
"""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.ast_engine import (
    CodebaseIndex,
    PythonASTExtractor,
    JSTSExtractor,
    build_codebase_index,
)
from scripts.compile import normalize_trace_data, TraceValidator, TraceCompiler


class TestASTEngine(unittest.TestCase):
    """Tests for scripts/ast_engine.py."""

    def test_python_ast_extraction(self):
        code = """
import os
from pathlib import Path

class WorkerManager:
    def __init__(self, name):
        self.name = name

    def start_worker(self):
        self.cleanup()
        return os.getpid()

    def cleanup(self):
        pass

def standalone_task():
    wm = WorkerManager("task-1")
    return wm.start_worker()
"""
        lines = code.strip().splitlines()
        import ast
        tree = ast.parse(code)
        extractor = PythonASTExtractor(file_path="sample.py", source_lines=lines)
        extractor.visit(tree)

        sym_names = [s.name for s in extractor.symbols]
        self.assertIn("WorkerManager", sym_names)
        self.assertIn("start_worker", sym_names)
        self.assertIn("cleanup", sym_names)
        self.assertIn("standalone_task", sym_names)

        # Check call extraction
        start_worker_sym = next(s for s in extractor.symbols if s.name == "start_worker")
        call_names = [c.callee_name for c in start_worker_sym.calls]
        self.assertIn("self.cleanup", call_names)
        self.assertIn("os.getpid", call_names)

    def test_jsts_ast_extraction(self):
        js_code = """
import { authService } from './auth';

export class SessionRouter {
  handleRequest(req, res) {
    const user = authService.verifyToken(req.token);
    this.dispatch(user);
  }

  dispatch(user) {
    return user.id;
  }
}

export const helperFunction = (x) => {
  return x * 2;
};
"""
        extractor = JSTSExtractor(file_path="router.js", content=js_code)
        symbols, imports = extractor.extract()

        sym_names = [s.name for s in symbols]
        self.assertIn("SessionRouter", sym_names)
        self.assertIn("helperFunction", sym_names)

    def test_call_edge_verification(self):
        # Index this actual trailblazer repo
        index = build_codebase_index(REPO_ROOT)
        self.assertGreater(len(index.symbols), 10)

        # handle_validate in server.py calls subprocess.run
        res = index.check_call_edge(
            source_file="mcp-server/server.py",
            source_symbol="handle_validate",
            target_symbol="subprocess.run"
        )
        self.assertTrue(res["connected"])
        self.assertTrue(res["direct"])
        self.assertGreaterEqual(res["confidence"], 0.9)


class TestDialecticVerificationAndCompiler(unittest.TestCase):
    """Tests for dialectic verification block and compile.py."""

    def test_normalize_verification_block(self):
        raw_data = {
            "repository": "test/repo",
            "verification": {
                "confidence": 0.95
            }
        }
        normalized = normalize_trace_data(raw_data)
        self.assertEqual(normalized["verification"]["confidenceScore"], 95)
        self.assertEqual(normalized["verification"]["status"], "verified")

    def test_compile_with_verification(self):
        trace_path = REPO_ROOT / "examples" / "example-trace.json"
        template_path = REPO_ROOT / "assets" / "template.html"
        self.assertTrue(trace_path.exists())
        self.assertTrue(template_path.exists())

        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
        validator = TraceValidator(trace_data)
        errors, warnings = validator.validate()
        self.assertEqual(len(errors), 0, f"Validation errors: {errors}")

        # Check verification fields
        self.assertIn("verification", validator.data)
        ver = validator.data["verification"]
        self.assertEqual(ver["status"], "verified")
        self.assertGreaterEqual(ver["confidenceScore"], 90)
        self.assertIn("adversarialChallenges", ver)


class TestMCPTools(unittest.TestCase):
    """Integration test calling MCP tools via stdio."""

    def test_mcp_new_tools_registration(self):
        server_path = REPO_ROOT / "mcp-server" / "server.py"
        req = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}) + "\n"

        proc = subprocess.run(
            [sys.executable, str(server_path)],
            input=req,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        resp = json.loads(proc.stdout.strip())
        tool_names = [t["name"] for t in resp["result"]["tools"]]

        self.assertIn("trailblazer_find_symbols", tool_names)
        self.assertIn("trailblazer_ground_ast", tool_names)
        self.assertIn("trailblazer_challenge_stop", tool_names)

    def test_mcp_challenge_stop_invocation(self):
        server_path = REPO_ROOT / "mcp-server" / "server.py"
        call_req = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "trailblazer_challenge_stop",
                "arguments": {
                    "stop_id": "stop-2",
                    "file": "scripts/compile.py",
                    "lines": "156-169",
                    "claim": "validate method processes data without null check"
                }
            }
        }
        proc = subprocess.run(
            [sys.executable, str(server_path)],
            input=json.dumps(call_req) + "\n",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        self.assertEqual(proc.returncode, 0)
        resp = json.loads(proc.stdout.strip())
        tool_content = json.loads(resp["result"]["content"][0]["text"])
        self.assertIn("prosecutor_challenges", tool_content)
        self.assertGreater(len(tool_content["prosecutor_challenges"]), 0)


if __name__ == "__main__":
    unittest.main()
