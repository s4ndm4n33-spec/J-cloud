# Copyright (c) 2024-2026 Sovereign Shards. Five Masters AST governance.
"""Five Masters Code Governance - AST-based analysis.

Ported from sovereign-shards/core/fivemasters.py.

Masters:
  Korotkevich - Efficiency: detect wasteful patterns
  Torvalds    - Error Handling: catch unsafe exception patterns
  Carmack     - Performance: spot structural anti-patterns
  Hamilton    - Fault Tolerance: verify defensive coding
  Ritchie     - Clarity: enforce naming and structure conventions
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Issue:
    master: str
    line: int
    message: str
    severity: str = "warning"  # "warning" | "error"


@dataclass
class FiveMastersReport:
    korotkevich: bool
    torvalds: bool
    carmack: bool
    hamilton: bool
    ritchie: bool
    issues: list[Issue] = field(default_factory=list)
    language: str = "python"

    def score(self) -> int:
        return sum([
            self.korotkevich,
            self.torvalds,
            self.carmack,
            self.hamilton,
            self.ritchie,
        ])

    def to_dict(self) -> dict[str, Any]:
        return {
            "korotkevich": self.korotkevich,
            "torvalds": self.torvalds,
            "carmack": self.carmack,
            "hamilton": self.hamilton,
            "ritchie": self.ritchie,
            "score": self.score(),
            "language": self.language,
            "issues": [asdict(i) for i in self.issues],
            "masters": [
                {"key": "korotkevich", "label": "Efficiency", "passed": self.korotkevich},
                {"key": "torvalds", "label": "Error Handling", "passed": self.torvalds},
                {"key": "carmack", "label": "Performance", "passed": self.carmack},
                {"key": "hamilton", "label": "Fault Tolerance", "passed": self.hamilton},
                {"key": "ritchie", "label": "Clarity", "passed": self.ritchie},
            ],
        }


# AST Visitors


class _KorotkevichVisitor(ast.NodeVisitor):
    """Efficiency: detect wasteful patterns."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def visit_For(self, node: ast.For) -> None:
        if (isinstance(node.iter, ast.Call)
                and isinstance(node.iter.func, ast.Name)
                and node.iter.func.id == "range"
                and len(node.iter.args) == 1):
            arg = node.iter.args[0]
            if (isinstance(arg, ast.Call)
                    and isinstance(arg.func, ast.Name)
                    and arg.func.id == "len"):
                self.issues.append(Issue(
                    "korotkevich", node.lineno,
                    "for i in range(len(x)) - use enumerate() or iterate directly"))

        nested_depth = 0
        for child in ast.walk(node):
            if child is not node and isinstance(child, ast.For):
                nested_depth += 1
        if nested_depth >= 2:
            self.issues.append(Issue(
                "korotkevich", node.lineno,
                "Triple-nested loop detected - review for O(n^3) complexity",
                severity="error"))

        self.generic_visit(node)


class _TorvaldsVisitor(ast.NodeVisitor):
    """Error Handling: detect unsafe exception patterns."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.type is None:
            self.issues.append(Issue(
                "torvalds", node.lineno,
                "Bare except: - catches KeyboardInterrupt and SystemExit"))

        if (node.type and isinstance(node.type, ast.Name)
                and node.type.id == "Exception"):
            body_has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(node))
            body_has_log = False
            for n in ast.walk(node):
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
                    if n.func.attr in ("error", "warning", "exception", "critical"):
                        body_has_log = True
                        break
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Name):
                    if n.func.id == "print":
                        body_has_log = True
                        break
            if not body_has_raise and not body_has_log:
                self.issues.append(Issue(
                    "torvalds", node.lineno,
                    "except Exception without re-raise or logging - errors silenced"))

        if (node.type is None
                and len(node.body) == 1
                and isinstance(node.body[0], ast.Pass)):
            self.issues.append(Issue(
                "torvalds", node.lineno,
                "except: pass - silently swallows all errors",
                severity="error"))

        self.generic_visit(node)


class _CarmackVisitor(ast.NodeVisitor):
    """Performance: detect structural anti-patterns."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        for default in node.args.defaults + node.args.kw_defaults:
            if default and isinstance(default, (ast.List, ast.Dict, ast.Set)):
                self.issues.append(Issue(
                    "carmack", node.lineno,
                    f"Mutable default arg in {node.name}() - shared across calls"))

        max_depth = _max_nesting_depth(node, 0)
        if max_depth > 4:
            self.issues.append(Issue(
                "carmack", node.lineno,
                f"{node.name}() has {max_depth} nesting levels - consider refactoring"))

        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore

    def visit_Global(self, node: ast.Global) -> None:
        self.issues.append(Issue(
            "carmack", node.lineno,
            f"global {', '.join(node.names)} - prefer parameter passing"))
        self.generic_visit(node)


class _HamiltonVisitor(ast.NodeVisitor):
    """Fault Tolerance: verify defensive coding."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []
        self._file_ops: list[int] = []

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            self._file_ops.append(node.lineno)
        if isinstance(node.func, ast.Attribute):
            if node.func.attr in ("urlopen", "connect", "send", "recv"):
                self._file_ops.append(node.lineno)
        self.generic_visit(node)

    def finalize(self, tree: ast.Module) -> None:
        try_ranges: list[tuple[int, int]] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                end = max(
                    (getattr(n, "lineno", node.lineno) for n in ast.walk(node)),
                    default=node.lineno,
                )
                try_ranges.append((node.lineno, end))

        for op_line in self._file_ops:
            guarded = any(start <= op_line <= end for start, end in try_ranges)
            if not guarded:
                self.issues.append(Issue(
                    "hamilton", op_line,
                    "I/O operation without try/except guard"))


class _RitchieVisitor(ast.NodeVisitor):
    """Clarity: naming conventions and structure."""

    def __init__(self) -> None:
        self.issues: list[Issue] = []

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node.end_lineno and node.lineno:
            length = node.end_lineno - node.lineno
            if length > 60:
                self.issues.append(Issue(
                    "ritchie", node.lineno,
                    f"{node.name}() is {length} lines - consider splitting"))

        if not node.name.startswith("_"):
            if node.name != node.name.lower() and "_" not in node.name:
                if not node.name.isupper():
                    self.issues.append(Issue(
                        "ritchie", node.lineno,
                        f"{node.name}() - use snake_case for functions"))

        self.generic_visit(node)

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node.name[0].islower():
            self.issues.append(Issue(
                "ritchie", node.lineno,
                f"class {node.name} - use PascalCase for classes"))
        self.generic_visit(node)


def _max_nesting_depth(node: ast.AST, current: int) -> int:
    max_d = current
    for child in ast.iter_child_nodes(node):
        if isinstance(child, (ast.If, ast.For, ast.While, ast.With,
                              ast.Try, ast.AsyncFor, ast.AsyncWith)):
            d = _max_nesting_depth(child, current + 1)
            max_d = max(max_d, d)
        else:
            d = _max_nesting_depth(child, current)
            max_d = max(max_d, d)
    return max_d


# Public API


def evaluate_python(code: str) -> FiveMastersReport:
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return FiveMastersReport(
            korotkevich=False, torvalds=False, carmack=False,
            hamilton=False, ritchie=False,
            issues=[Issue("ritchie", e.lineno or 0,
                          f"SyntaxError: {e.msg}", severity="error")],
            language="python",
        )

    all_issues: list[Issue] = []

    k = _KorotkevichVisitor(); k.visit(tree); all_issues.extend(k.issues)
    t = _TorvaldsVisitor(); t.visit(tree); all_issues.extend(t.issues)
    c = _CarmackVisitor(); c.visit(tree); all_issues.extend(c.issues)
    h = _HamiltonVisitor(); h.visit(tree); h.finalize(tree); all_issues.extend(h.issues)
    r = _RitchieVisitor(); r.visit(tree); all_issues.extend(r.issues)

    def _master_pass(name: str) -> bool:
        errors = [i for i in all_issues if i.master == name and i.severity == "error"]
        warnings_ = [i for i in all_issues if i.master == name and i.severity == "warning"]
        return len(errors) == 0 and len(warnings_) <= 2

    return FiveMastersReport(
        korotkevich=_master_pass("korotkevich"),
        torvalds=_master_pass("torvalds"),
        carmack=_master_pass("carmack"),
        hamilton=_master_pass("hamilton"),
        ritchie=_master_pass("ritchie"),
        issues=all_issues,
        language="python",
    )


def evaluate_heuristic(code: str, language: str) -> FiveMastersReport:
    """Cheap heuristic for non-Python files (JS/TS/etc)."""
    issues: list[Issue] = []
    lines = code.split("\n")

    korotkevich = True
    torvalds = True
    carmack = True
    hamilton = True
    ritchie = True

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if "console.log" in stripped and language in ("javascript", "typescript", "js", "ts"):
            issues.append(Issue("ritchie", i, "Stray console.log()"))
            ritchie = False
        if " == " in stripped and language in ("javascript", "typescript", "js", "ts"):
            issues.append(Issue("torvalds", i, "Use === instead of =="))
            torvalds = False
        if "var " in stripped and language in ("javascript", "typescript", "js", "ts"):
            issues.append(Issue("ritchie", i, "Use let/const, not var"))
            ritchie = False
        if "TODO" in stripped or "FIXME" in stripped:
            issues.append(Issue("hamilton", i, "Unresolved TODO/FIXME"))
            hamilton = False
        if "any" == stripped or ": any" in stripped:
            if language in ("typescript", "ts"):
                issues.append(Issue("ritchie", i, "Avoid `any` - use explicit types"))
                ritchie = False
        if "catch" in stripped and "{}" in stripped:
            issues.append(Issue("torvalds", i, "Empty catch block - errors silenced"))
            torvalds = False

    if len(lines) > 400:
        issues.append(Issue("ritchie", 1, f"File is {len(lines)} lines - consider splitting"))
        ritchie = False

    return FiveMastersReport(
        korotkevich=korotkevich,
        torvalds=torvalds,
        carmack=carmack,
        hamilton=hamilton,
        ritchie=ritchie,
        issues=issues,
        language=language,
    )


def evaluate(code: str, language: str = "python") -> FiveMastersReport:
    """Universal entry point. Routes to AST if Python, else heuristic."""
    if language.lower() in ("python", "py"):
        return evaluate_python(code)
    return evaluate_heuristic(code, language.lower())
