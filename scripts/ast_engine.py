#!/usr/bin/env python3
"""
Trailblazer AST & Call-Graph Grounding Engine

Provides zero-dependency static AST parsing, symbol indexing, caller-callee call-graph
extraction, and empirical path verification for AI codebase investigations.

Supported languages:
  - Python (via native standard library `ast` module)
  - JavaScript / TypeScript (via regex & structural token parsing)
  - Generic / Polyglot fallback (heuristic symbol & invocation matching)
"""

from __future__ import annotations

import ast
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class CallSite:
    callee_name: str
    line_no: int
    raw_expr: str


@dataclass
class Symbol:
    name: str
    kind: str  # "function" | "async_function" | "class" | "method"
    file_path: str  # relative to repo root
    start_line: int
    end_line: int
    parent_class: Optional[str] = None
    calls: List[CallSite] = field(default_factory=list)
    docstring: Optional[str] = None

    @property
    def qualified_name(self) -> str:
        if self.parent_class:
            return f"{self.parent_class}.{self.name}"
        return self.name

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "parent_class": self.parent_class,
            "calls": [asdict(c) for c in self.calls],
            "docstring": self.docstring,
        }


@dataclass
class ImportStatement:
    file_path: str
    line_no: int
    module: str
    names: List[str] = field(default_factory=list)
    is_from_import: bool = False


class PythonASTExtractor(ast.NodeVisitor):
    """Extracts symbols, methods, classes, and call expressions from Python code."""

    def __init__(self, file_path: str, source_lines: List[str]):
        self.file_path = file_path
        self.source_lines = source_lines
        self.symbols: List[Symbol] = []
        self.imports: List[ImportStatement] = []
        self.current_class: Optional[str] = None
        self.current_symbol: Optional[Symbol] = None

    def visit_Import(self, node: ast.Import):
        names = [alias.name for alias in node.names]
        self.imports.append(
            ImportStatement(
                file_path=self.file_path,
                line_no=node.lineno,
                module=", ".join(names),
                names=names,
                is_from_import=False,
            )
        )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = node.module or ""
        names = [alias.name for alias in node.names]
        self.imports.append(
            ImportStatement(
                file_path=self.file_path,
                line_no=node.lineno,
                module=module,
                names=names,
                is_from_import=True,
            )
        )
        self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef):
        prev_class = self.current_class
        self.current_class = node.name

        doc = ast.get_docstring(node)
        end_line = getattr(node, "end_lineno", node.lineno)
        class_symbol = Symbol(
            name=node.name,
            kind="class",
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=end_line,
            docstring=doc,
        )
        self.symbols.append(class_symbol)

        self.generic_visit(node)
        self.current_class = prev_class

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._handle_function(node, is_async=False)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._handle_function(node, is_async=True)

    def _handle_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef, is_async: bool):
        kind = "method" if self.current_class else ("async_function" if is_async else "function")
        end_line = getattr(node, "end_lineno", node.lineno)
        doc = ast.get_docstring(node)

        sym = Symbol(
            name=node.name,
            kind=kind,
            file_path=self.file_path,
            start_line=node.lineno,
            end_line=end_line,
            parent_class=self.current_class,
            docstring=doc,
        )

        prev_symbol = self.current_symbol
        self.current_symbol = sym

        # Visit children to collect calls made within this function
        for child in node.body:
            self.visit(child)

        self.symbols.append(sym)
        self.current_symbol = prev_symbol

    def visit_Call(self, node: ast.Call):
        if self.current_symbol:
            callee_name = self._resolve_callee_name(node.func)
            if callee_name:
                raw_expr = ""
                if 0 <= node.lineno - 1 < len(self.source_lines):
                    raw_expr = self.source_lines[node.lineno - 1].strip()
                self.current_symbol.calls.append(
                    CallSite(callee_name=callee_name, line_no=node.lineno, raw_expr=raw_expr)
                )
        self.generic_visit(node)

    def _resolve_callee_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            val = self._resolve_callee_name(node.value)
            if val:
                return f"{val}.{node.attr}"
            return node.attr
        return None


class JSTSExtractor:
    """Lightweight regex/token scanner for JavaScript and TypeScript files."""

    FUNC_DEF_PATTERN = re.compile(
        r"(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z0-9_$]+)\s*\(", re.MULTILINE
    )
    ARROW_CONST_PATTERN = re.compile(
        r"(?:export\s+)?(?:const|let|var)\s+([a-zA-Z0-9_$]+)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z0-9_$]+)\s*=>",
        re.MULTILINE,
    )
    CLASS_DEF_PATTERN = re.compile(
        r"(?:export\s+)?class\s+([a-zA-Z0-9_$]+)(?:\s+extends\s+[a-zA-Z0-9_$]+)?\s*\{",
        re.MULTILINE,
    )
    METHOD_DEF_PATTERN = re.compile(
        r"^\s*(?:async\s+)?([a-zA-Z0-9_$]+)\s*\([^)]*\)\s*\{", re.MULTILINE
    )
    CALL_PATTERN = re.compile(r"([a-zA-Z0-9_$.]+)\s*\(", re.MULTILINE)
    IMPORT_PATTERN = re.compile(
        r"import\s+(?:(?:\*\s+as\s+[a-zA-Z0-9_$]+)|(?:\{[^}]+\})|(?:[a-zA-Z0-9_$]+))\s+from\s+['\"]([^'\"]+)['\"]",
        re.MULTILINE,
    )

    def __init__(self, file_path: str, content: str):
        self.file_path = file_path
        self.content = content
        self.lines = content.splitlines()

    def extract(self) -> Tuple[List[Symbol], List[ImportStatement]]:
        symbols: List[Symbol] = []
        imports: List[ImportStatement] = []

        # Find imports
        for i, line in enumerate(self.lines, start=1):
            imp_match = self.IMPORT_PATTERN.search(line)
            if imp_match:
                module = imp_match.group(1)
                imports.append(
                    ImportStatement(
                        file_path=self.file_path,
                        line_no=i,
                        module=module,
                        names=[],
                        is_from_import=True,
                    )
                )

        # Find functions
        for i, line in enumerate(self.lines, start=1):
            m = self.FUNC_DEF_PATTERN.search(line)
            if not m:
                m = self.ARROW_CONST_PATTERN.search(line)

            if m:
                name = m.group(1)
                # approximate end line using simple bracket count or fixed window
                end_line = self._find_closing_bracket(i - 1)
                sym = Symbol(
                    name=name,
                    kind="function",
                    file_path=self.file_path,
                    start_line=i,
                    end_line=end_line,
                )
                self._extract_calls_in_range(sym, i, end_line)
                symbols.append(sym)
                continue

            cm = self.CLASS_DEF_PATTERN.search(line)
            if cm:
                name = cm.group(1)
                end_line = self._find_closing_bracket(i - 1)
                symbols.append(
                    Symbol(
                        name=name,
                        kind="class",
                        file_path=self.file_path,
                        start_line=i,
                        end_line=end_line,
                    )
                )

        return symbols, imports

    def _find_closing_bracket(self, start_idx: int) -> int:
        open_brackets = 0
        found_open = False
        for idx in range(start_idx, len(self.lines)):
            line = self.lines[idx]
            for ch in line:
                if ch == "{":
                    open_brackets += 1
                    found_open = True
                elif ch == "}":
                    open_brackets -= 1
                    if found_open and open_brackets <= 0:
                        return idx + 1
        return min(start_idx + 30, len(self.lines))

    def _extract_calls_in_range(self, symbol: Symbol, start_line: int, end_line: int):
        for line_no in range(start_line, min(end_line + 1, len(self.lines) + 1)):
            line = self.lines[line_no - 1]
            # Strip keywords like if (, for (, while (, function (
            for match in self.CALL_PATTERN.finditer(line):
                callee = match.group(1)
                if callee not in {"if", "for", "while", "switch", "catch", "function", "return"}:
                    symbol.calls.append(
                        CallSite(callee_name=callee, line_no=line_no, raw_expr=line.strip())
                    )


class CodebaseIndex:
    """In-memory index of symbols, imports, and call relationships across a codebase."""

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        self.symbols: List[Symbol] = []
        self.imports: List[ImportStatement] = []
        self.symbols_by_name: Dict[str, List[Symbol]] = {}
        self.symbols_by_file: Dict[str, List[Symbol]] = {}
        self.imports_by_file: Dict[str, List[ImportStatement]] = {}
        self.indexed_files: Set[str] = set()

    def add_symbol(self, sym: Symbol):
        self.symbols.append(sym)
        self.symbols_by_name.setdefault(sym.name, []).append(sym)
        if sym.qualified_name != sym.name:
            self.symbols_by_name.setdefault(sym.qualified_name, []).append(sym)
        self.symbols_by_file.setdefault(sym.file_path, []).append(sym)

    def add_import(self, imp: ImportStatement):
        self.imports.append(imp)
        self.imports_by_file.setdefault(imp.file_path, []).append(imp)

    def find_symbols(
        self, query: str, file_pattern: Optional[str] = None, exact: bool = False
    ) -> List[Symbol]:
        results: List[Symbol] = []
        q = query.lower()

        for sym in self.symbols:
            if file_pattern and not self._match_pattern(sym.file_path, file_pattern):
                continue

            if exact:
                if sym.name == query or sym.qualified_name == query:
                    results.append(sym)
            else:
                if q in sym.name.lower() or q in sym.qualified_name.lower():
                    results.append(sym)
        return results

    def find_symbol_at_line(self, file_path: str, line_no: int) -> Optional[Symbol]:
        norm_path = self._normalize_path(file_path)
        file_syms = self.symbols_by_file.get(norm_path, [])
        matching = [s for s in file_syms if s.start_line <= line_no <= s.end_line]
        if not matching:
            return None
        # Return the most specific (innermost) symbol with shortest line range
        return min(matching, key=lambda s: (s.end_line - s.start_line))

    def check_call_edge(
        self,
        source_file: str,
        source_symbol: str,
        target_file: Optional[str] = None,
        target_symbol: Optional[str] = None,
        max_hops: int = 3,
    ) -> Dict[str, Any]:
        """Verifies if source_symbol in source_file can statically reach target_symbol."""
        norm_src_path = self._normalize_path(source_file)
        norm_tgt_path = self._normalize_path(target_file) if target_file else None

        # Find source symbol
        src_syms = [
            s
            for s in self.symbols_by_file.get(norm_src_path, [])
            if s.name == source_symbol or s.qualified_name == source_symbol
        ]
        if not src_syms:
            # Try fuzzy match in file
            src_syms = [
                s
                for s in self.symbols_by_file.get(norm_src_path, [])
                if source_symbol.lower() in s.name.lower()
            ]

        if not src_syms:
            return {
                "connected": False,
                "confidence": 0.0,
                "reason": f"Source symbol '{source_symbol}' not found in '{source_file}'",
                "direct": False,
                "path": [],
            }

        src_sym = src_syms[0]

        # Check 1: Direct call from source symbol to target symbol
        if target_symbol:
            tgt_base = target_symbol.split(".")[-1]
            for call in src_sym.calls:
                call_base = call.callee_name.split(".")[-1]
                if (
                    call_base == tgt_base
                    or call.callee_name == target_symbol
                    or target_symbol in call.callee_name
                ):
                    return {
                        "connected": True,
                        "confidence": 0.95,
                        "direct": True,
                        "reason": f"Direct call from '{src_sym.qualified_name}' to '{call.callee_name}' on line {call.line_no}",
                        "callSite": asdict(call),
                        "path": [src_sym.qualified_name, target_symbol],
                    }

        # Check 2: File-level import connectivity
        has_import = False
        if norm_tgt_path:
            file_imports = self.imports_by_file.get(norm_src_path, [])
            tgt_module_stem = Path(norm_tgt_path).stem
            for imp in file_imports:
                if tgt_module_stem in imp.module or (target_symbol and target_symbol in imp.names):
                    has_import = True
                    break

        # Check 3: Multi-hop graph search (BFS up to max_hops)
        if target_symbol:
            path = self._search_call_path(src_sym, target_symbol, max_hops=max_hops)
            if path:
                return {
                    "connected": True,
                    "confidence": 0.85 if has_import else 0.75,
                    "direct": False,
                    "reason": f"Call chain path discovered ({len(path)-1} hops)",
                    "path": path,
                }

        # If import exists between the files, acknowledge module linkage
        if has_import:
            return {
                "connected": True,
                "confidence": 0.65,
                "direct": False,
                "reason": f"File '{source_file}' imports module from '{target_file}', but no direct call site to '{target_symbol}' was verified.",
                "path": [src_sym.qualified_name, f"import({norm_tgt_path})", target_symbol or ""],
            }

        return {
            "connected": False,
            "confidence": 0.1,
            "direct": False,
            "reason": f"No static call edge or import connection found between '{source_symbol}' and '{target_symbol or target_file}'",
            "path": [],
        }

    def _search_call_path(
        self, start_sym: Symbol, target_symbol_name: str, max_hops: int = 3
    ) -> Optional[List[str]]:
        """Breadth-first search for a call chain leading to target_symbol_name."""
        target_base = target_symbol_name.split(".")[-1]
        queue: List[Tuple[Symbol, List[str]]] = [(start_sym, [start_sym.qualified_name])]
        visited: Set[str] = {f"{start_sym.file_path}:{start_sym.qualified_name}"}

        while queue:
            curr_sym, curr_path = queue.pop(0)
            if len(curr_path) > max_hops + 1:
                continue

            for call in curr_sym.calls:
                callee_base = call.callee_name.split(".")[-1]
                if callee_base == target_base or call.callee_name == target_symbol_name:
                    return curr_path + [target_symbol_name]

                # Expand next symbols
                next_candidates = self.symbols_by_name.get(callee_base, [])
                for nxt in next_candidates:
                    key = f"{nxt.file_path}:{nxt.qualified_name}"
                    if key not in visited:
                        visited.add(key)
                        queue.append((nxt, curr_path + [nxt.qualified_name]))

        return None

    def verify_trace(self, trace_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validates trace stops against the AST symbol graph.
        Checks:
          1. Stop file and line ranges align with actual AST symbols.
          2. Consecutive stops have static call edges, import ties, or explicit transitions.
        """
        stops = trace_data.get("trail") or trace_data.get("stops") or []
        issues: List[Dict[str, Any]] = []
        verified_stops = 0
        total_stops = len(stops)
        verified_edges = 0
        possible_edges = max(0, total_stops - 1)

        stop_symbols: List[Optional[Symbol]] = []

        for idx, stop in enumerate(stops):
            fpath = stop.get("file") or stop.get("path") or ""
            start_line = stop.get("lineStart")
            if start_line is None:
                lines = str(stop.get("lines", "0"))
                if "-" in lines:
                    try:
                        start_line = int(lines.split("-")[0].strip())
                    except ValueError:
                        start_line = 0
                else:
                    try:
                        start_line = int(lines.strip())
                    except ValueError:
                        start_line = 0
                if start_line == 0 and stop.get("highlightLines"):
                    start_line = stop["highlightLines"][0]

            sym = self.find_symbol_at_line(fpath, start_line) if start_line and start_line > 0 else None
            stop_symbols.append(sym)

            if sym:
                verified_stops += 1
            else:
                norm_f = self._normalize_path(fpath)
                if norm_f in self.indexed_files:
                    issues.append(
                        {
                            "severity": "info",
                            "stop_id": stop.get("id", f"stop-{idx+1}"),
                            "message": f"Lines {start_line} in '{fpath}' do not cleanly map to a single function/class AST boundary.",
                        }
                    )
                else:
                    issues.append(
                        {
                            "severity": "warning",
                            "stop_id": stop.get("id", f"stop-{idx+1}"),
                            "message": f"File '{fpath}' not indexed or outside repository root.",
                        }
                    )

        # Check edge continuity between consecutive stops
        edge_results: List[Dict[str, Any]] = []
        for i in range(len(stops) - 1):
            s1 = stops[i]
            s2 = stops[i + 1]
            sym1 = stop_symbols[i]
            sym2 = stop_symbols[i + 1]

            if sym1 and sym2:
                edge_res = self.check_call_edge(
                    source_file=s1.get("file", ""),
                    source_symbol=sym1.name,
                    target_file=s2.get("file", ""),
                    target_symbol=sym2.name,
                )
                edge_results.append(
                    {
                        "from_stop": s1.get("id", f"stop-{i+1}"),
                        "to_stop": s2.get("id", f"stop-{i+2}"),
                        "from_symbol": sym1.qualified_name,
                        "to_symbol": sym2.qualified_name,
                        **edge_res,
                    }
                )
                if edge_res.get("connected"):
                    verified_edges += 1
            else:
                edge_results.append(
                    {
                        "from_stop": s1.get("id", f"stop-{i+1}"),
                        "to_stop": s2.get("id", f"stop-{i+2}"),
                        "connected": False,
                        "confidence": 0.5,
                        "reason": "One or both stops could not be resolved to precise AST symbols.",
                    }
                )

        stop_score = (verified_stops / total_stops) if total_stops > 0 else 1.0
        edge_score = (verified_edges / possible_edges) if possible_edges > 0 else 1.0
        overall_grounding = round((stop_score * 0.4 + edge_score * 0.6) * 100, 1)

        return {
            "grounding_score": overall_grounding,
            "total_stops": total_stops,
            "verified_stops": verified_stops,
            "possible_edges": possible_edges,
            "verified_edges": verified_edges,
            "edge_results": edge_results,
            "issues": issues,
        }

    def _normalize_path(self, path_str: str) -> str:
        p = Path(path_str)
        if p.is_absolute():
            try:
                return str(p.relative_to(self.root_dir))
            except ValueError:
                return p.name
        return str(p)

    def _match_pattern(self, path_str: str, pattern: str) -> bool:
        return pattern.lower() in path_str.lower()


def build_codebase_index(
    root_dir: Path | str,
    max_files: int = 1500,
    ignore_dirs: Optional[Set[str]] = None,
) -> CodebaseIndex:
    """Recursively scans and parses Python, JS, TS, and related files into an AST Index."""
    root_path = Path(root_dir).resolve()
    index = CodebaseIndex(root_path)

    if ignore_dirs is None:
        ignore_dirs = {
            ".git",
            "node_modules",
            "__pycache__",
            ".venv",
            "venv",
            "env",
            "dist",
            "build",
            ".idea",
            ".vscode",
            ".claude",
        }

    file_count = 0

    for current_dir, dirs, files in os.walk(root_path):
        # Prune ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]

        for filename in files:
            if file_count >= max_files:
                break

            file_path = Path(current_dir) / filename
            rel_path = str(file_path.relative_to(root_path))
            suffix = file_path.suffix.lower()

            if suffix == ".py":
                _parse_python_file(file_path, rel_path, index)
                index.indexed_files.add(rel_path)
                file_count += 1
            elif suffix in {".js", ".jsx", ".ts", ".tsx", ".mjs"}:
                _parse_jsts_file(file_path, rel_path, index)
                index.indexed_files.add(rel_path)
                file_count += 1

    return index


def _parse_python_file(file_path: Path, rel_path: str, index: CodebaseIndex):
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(content, filename=str(file_path))
        lines = content.splitlines()
        extractor = PythonASTExtractor(file_path=rel_path, source_lines=lines)
        extractor.visit(tree)

        for sym in extractor.symbols:
            index.add_symbol(sym)
        for imp in extractor.imports:
            index.add_import(imp)
    except Exception:
        # Graceful fallback on syntax or parse errors
        pass


def _parse_jsts_file(file_path: Path, rel_path: str, index: CodebaseIndex):
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
        extractor = JSTSExtractor(file_path=rel_path, content=content)
        symbols, imports = extractor.extract()

        for sym in symbols:
            index.add_symbol(sym)
        for imp in imports:
            index.add_import(imp)
    except Exception:
        pass


# ==============================================================================
# CLI Entry Point
# ==============================================================================


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Trailblazer AST & Call-Graph Grounding Engine")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # Command: index
    index_parser = subparsers.add_parser("index", help="Index codebase and print summary statistics")
    index_parser.add_argument("path", nargs="?", default=".", help="Root directory of codebase")

    # Command: find-symbol
    find_parser = subparsers.add_parser("find-symbol", help="Search for functions or classes")
    find_parser.add_argument("query", help="Symbol name or pattern")
    find_parser.add_argument("--path", default=".", help="Root directory of codebase")
    find_parser.add_argument("--file", default=None, help="File pattern filter")

    # Command: check-edge
    edge_parser = subparsers.add_parser("check-edge", help="Check static call edge between two symbols")
    edge_parser.add_argument("--source-file", required=True, help="File containing source symbol")
    edge_parser.add_argument("--source-symbol", required=True, help="Name of source symbol")
    edge_parser.add_argument("--target-file", default=None, help="File containing target symbol")
    edge_parser.add_argument("--target-symbol", default=None, help="Name of target symbol")
    edge_parser.add_argument("--path", default=".", help="Root directory of codebase")

    # Command: ground-trace
    trace_parser = subparsers.add_parser("ground-trace", help="Verify a trace.json file against codebase AST")
    trace_parser.add_argument("trace_file", help="Path to trace.json")
    trace_parser.add_argument("--path", default=".", help="Root directory of codebase")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    root_dir = Path(args.path).resolve()
    index = build_codebase_index(root_dir)

    if args.command == "index":
        print(f"✅ Indexed {len(index.indexed_files)} files in '{root_dir}'")
        print(f"📊 Total symbols discovered: {len(index.symbols)}")
        print(f"📦 Total imports tracked: {len(index.imports)}")
        func_count = sum(1 for s in index.symbols if "function" in s.kind or s.kind == "method")
        class_count = sum(1 for s in index.symbols if s.kind == "class")
        print(f"   ├─ Functions/Methods: {func_count}")
        print(f"   └─ Classes: {class_count}")

    elif args.command == "find-symbol":
        syms = index.find_symbols(args.query, file_pattern=args.file)
        print(f"Found {len(syms)} symbol(s) matching '{args.query}':")
        for s in syms[:20]:
            print(f"  • [{s.kind}] {s.qualified_name} -> {s.file_path}:{s.start_line}-{s.end_line} ({len(s.calls)} calls)")

    elif args.command == "check-edge":
        res = index.check_call_edge(
            source_file=args.source_file,
            source_symbol=args.source_symbol,
            target_file=args.target_file,
            target_symbol=args.target_symbol,
        )
        print(json.dumps(res, indent=2))

    elif args.command == "ground-trace":
        trace_path = Path(args.trace_file).resolve()
        if not trace_path.exists():
            print(f"Error: Trace file '{trace_path}' not found", file=sys.stderr)
            sys.exit(1)
        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
        res = index.verify_trace(trace_data)
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
