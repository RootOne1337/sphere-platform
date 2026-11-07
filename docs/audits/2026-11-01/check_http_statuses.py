"""Read-only status-declaration candidate finder; not an API conformance test.

Run from any directory: python docs/audits/2026-11-01/check_http_statuses.py
Use --json for structured results. Match operationId to decorated function names
and canonical paths, then inspect explicit direct returns, status assignments and
HTTPException raises. Service errors, dynamic routing and runtime behavior are
outside this static scan; every candidate requires manual review.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
METHODS = {"get", "post", "put", "patch", "delete", "head", "options", "trace"}
RESPONSES = {"Response", "JSONResponse", "PlainTextResponse", "RedirectResponse"}


def name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return node.attr if isinstance(node, ast.Attribute) else ""


def codes(node: ast.AST) -> set[int]:
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return {node.value}
    if isinstance(node, ast.Attribute):
        found = re.fullmatch(r"HTTP_(\d{3})_.*", node.attr)
        return {int(found.group(1))} if found else set()
    if isinstance(node, ast.IfExp):
        return codes(node.body) | codes(node.orelse)
    return set()


class BodyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.observations: list[tuple[str, int, int]] = []
        self.unresolved: list[tuple[str, int]] = []

    def inspect_status(self, kind: str, line: int, node: ast.AST) -> None:
        values = codes(node)
        if not values:
            self.unresolved.append((kind, line))
        for value in sorted(values):
            self.observations.append((kind, line, value))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        pass  # A nested helper is not itself a handler return.

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Return(self, node: ast.Return) -> None:
        if isinstance(node.value, ast.Call) and name(node.value.func) in RESPONSES:
            for keyword in node.value.keywords:
                if keyword.arg == "status_code":
                    self.inspect_status("explicit_response", node.lineno, keyword.value)
        self.generic_visit(node)

    def visit_Raise(self, node: ast.Raise) -> None:
        if isinstance(node.exc, ast.Call) and name(node.exc.func) == "HTTPException":
            value = next((kw.value for kw in node.exc.keywords if kw.arg == "status_code"), None)
            if value is None and node.exc.args:
                value = node.exc.args[0]
            if value is not None:
                self.inspect_status("http_exception", node.lineno, value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        if any(isinstance(t, ast.Attribute) and t.attr == "status_code" for t in node.targets):
            self.inspect_status("status_assignment", node.lineno, node.value)
        self.generic_visit(node)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit structured candidates")
    args = parser.parse_args()
    paths = json.loads((ROOT / "docs/openapi.json").read_text(encoding="utf-8"))["paths"]
    ops = {(method, path): op for path, entries in paths.items()
           for method, op in entries.items() if method in METHODS}
    matched: set[tuple[str, str]] = set()
    candidates: list[dict] = []
    unresolved: list[dict] = []
    unreadable: list[str] = []
    for path in sorted((ROOT / "backend").rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, SyntaxError):
            unreadable.append(path.relative_to(ROOT).as_posix())
            continue
        for fn in (n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
            for dec in fn.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(dec.func, ast.Attribute):
                    continue
                method = dec.func.attr
                if method not in METHODS:
                    continue
                matches = [(key, op) for key, op in ops.items() if key[0] == method and
                           op.get("operationId") == fn.name + re.sub(r"\W", "_", key[1]) + "_" + method]
                if len(matches) != 1:
                    continue
                (method, route), op = matches[0]
                matched.add((method, route))
                declared = set(op.get("responses", {}))
                visitor = BodyVisitor()
                for statement in fn.body:
                    visitor.visit(statement)
                rel = path.relative_to(ROOT).as_posix()
                for kind, line, value in visitor.observations:
                    if str(value) not in declared and "default" not in declared and f"{value // 100}XX" not in declared:
                        candidates.append({"method": method.upper(), "path": route, "file": rel,
                                           "line": line, "kind": kind, "status": value,
                                           "declared": sorted(declared)})
                for kind, line in visitor.unresolved:
                    unresolved.append({"method": method.upper(), "path": route, "file": rel,
                                       "line": line, "kind": kind})
    output = {"snapshot_operations": len(ops), "matched_operations": len(matched),
              "unmatched_operations": [{"method": m.upper(), "path": p} for m, p in sorted(set(ops)-matched)],
              "candidates": sorted(candidates, key=lambda c: (c["path"], c["method"], c["line"])),
              "unresolved_expressions": unresolved, "unreadable_files": unreadable}
    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return
    print(f"Snapshot: {len(ops)} operations; statically matched: {len(matched)}; "
          f"unmatched: {len(ops)-len(matched)}; unresolved expressions: {len(unresolved)}")
    for item in output["candidates"]:
        print(f"{item['method']} {item['path']} -> {item['status']} ({item['kind']}), "
              f"declared {','.join(item['declared'])}; {item['file']}:{item['line']}")
    print("Candidates only: conditional branches, inherited responses and dynamic behavior require review.")


if __name__ == "__main__":
    main()
