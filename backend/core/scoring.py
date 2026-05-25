"""Project audit — deterministic 100-point Gauntlet score."""
from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path
from typing import Any

from .destructive import scan as destructive_scan
from .fivemasters import evaluate as fm_evaluate

CODE_EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".rs", ".go", ".java", ".rb", ".php", ".c", ".cpp"}


def _read_gauntletignore(root: Path) -> list[re.Pattern]:
    f = root / ".gauntletignore"
    if not f.exists():
        return []
    patterns: list[re.Pattern] = []
    for line in f.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # Convert glob-ish pattern to regex
        regex = re.escape(line).replace(r"\*\*", ".*").replace(r"\*", "[^/]*")
        patterns.append(re.compile(regex))
    return patterns


def _ignored(rel: str, patterns: list[re.Pattern]) -> bool:
    return any(p.search(rel) for p in patterns)


def _iter_code_files(root: Path, patterns: list[re.Pattern]) -> list[Path]:
    out: list[Path] = []
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if any(part in (".git", "node_modules", "__pycache__", ".venv", "dist", "build")
               for part in p.parts):
            continue
        if _ignored(rel, patterns):
            continue
        if p.suffix.lower() in CODE_EXTS:
            out.append(p)
    return out


def _typehint_coverage(files: list[Path]) -> float:
    total_funcs = 0
    typed_funcs = 0
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                total_funcs += 1
                has_return = node.returns is not None
                args_typed = all(a.annotation is not None for a in node.args.args
                                 if a.arg not in ("self", "cls"))
                if has_return and args_typed:
                    typed_funcs += 1
    if total_funcs == 0:
        return 1.0
    return typed_funcs / total_funcs


def _docstring_coverage(files: list[Path]) -> float:
    total = 0
    documented = 0
    for f in files:
        if f.suffix != ".py":
            continue
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError, UnicodeDecodeError):
            continue
        if ast.get_docstring(tree):
            documented += 1
        total += 1
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                if ast.get_docstring(node):
                    documented += 1
    if total == 0:
        return 1.0
    return documented / total


def _has_tests(root: Path) -> bool:
    if (root / "tests").exists() or (root / "test").exists() or (root / "__tests__").exists():
        return True
    for p in root.rglob("*test*.py"):
        if p.is_file():
            return True
    for p in root.rglob("*.test.*"):
        if p.is_file():
            return True
    return False


def _commit_count(root: Path) -> int:
    try:
        r = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=root,
                           capture_output=True, text=True, timeout=5)
        return int((r.stdout or "0").strip())
    except (subprocess.SubprocessError, OSError, ValueError):
        return 0


def audit_project(root: Path) -> dict[str, Any]:
    """Compute the 100-point Gauntlet project score with full breakdown."""
    patterns = _read_gauntletignore(root)
    code_files = _iter_code_files(root, patterns)

    # --- Five Masters AST average (40 pts) ---
    weighted = 0.0
    weight_total = 0.0
    file_reports: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    for f in code_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        lang = {
            ".py": "python", ".js": "javascript", ".jsx": "javascript",
            ".ts": "typescript", ".tsx": "typescript", ".rs": "rust",
            ".go": "go", ".java": "java", ".rb": "ruby", ".php": "php",
            ".c": "c", ".cpp": "cpp",
        }.get(f.suffix.lower(), "plaintext")
        rep = fm_evaluate(text, lang).to_dict()
        loc = max(1, len(text.splitlines()))
        weighted += (rep["score"] / 5.0) * loc
        weight_total += loc
        file_reports.append({
            "path": f.relative_to(root).as_posix(),
            "score": rep["score"],
            "issues": len(rep["issues"]),
            "language": lang,
        })
        for iss in rep["issues"][:3]:
            all_issues.append({**iss, "file": f.relative_to(root).as_posix()})
    ast_ratio = (weighted / weight_total) if weight_total else 1.0
    ast_pts = round(ast_ratio * 40, 1)

    # --- Destructive clean (15 pts) ---
    destructive_pts = 15.0
    destructive_findings: list[dict[str, Any]] = []
    for f in code_files:
        try:
            for m in destructive_scan(f.read_text(encoding="utf-8", errors="ignore")):
                destructive_findings.append({
                    "file": f.relative_to(root).as_posix(),
                    "pattern": m.pattern, "line": m.line, "severity": m.severity,
                    "reason": m.reason,
                })
                destructive_pts -= 5 if m.severity == "critical" else 3
        except OSError:
            pass
    destructive_pts = max(0.0, destructive_pts)

    # --- Documentation (10 pts) ---
    has_readme = any((root / n).exists() for n in ("README.md", "README.rst", "README.txt", "README"))
    doc_cov = _docstring_coverage(code_files)
    doc_pts = (5 if has_readme else 0) + round(doc_cov * 5, 1)

    # --- Tests (10 pts) ---
    test_pts = 10 if _has_tests(root) else 0

    # --- Type-hint coverage (10 pts) ---
    th_cov = _typehint_coverage(code_files)
    th_pts = round(th_cov * 10, 1)

    # --- Hygiene (10 pts) ---
    hyg_pts = 0
    hyg_pts += 3 if (root / ".gitignore").exists() else 0
    hyg_pts += 3 if any((root / n).exists() for n in ("LICENSE", "LICENSE.md", "LICENSE.txt")) else 0
    hyg_pts += 4 if _commit_count(root) >= 3 else (2 if _commit_count(root) >= 1 else 0)

    # --- Dependency sanity (5 pts) ---
    dep_pts = 0
    for n in ("requirements.txt", "package.json", "Cargo.toml", "go.mod", "pyproject.toml"):
        f = root / n
        if f.exists() and f.stat().st_size > 0:
            dep_pts = 5
            break

    total = round(ast_pts + destructive_pts + doc_pts + test_pts + th_pts + hyg_pts + dep_pts, 1)

    # Recommendations sorted by potential gain
    recs: list[dict[str, Any]] = []
    if ast_pts < 40:
        # Top 3 worst-scoring files
        worst = sorted(file_reports, key=lambda x: x["score"])[:3]
        for w in worst:
            if w["issues"] > 0:
                recs.append({
                    "category": "five_masters",
                    "title": f"Refactor {w['path']} (Five Masters {w['score']}/5)",
                    "potential_gain": round((1 - w["score"] / 5) * (40 / max(1, len(file_reports))), 1),
                    "target_file": w["path"],
                })
    if not has_readme:
        recs.append({"category": "docs", "title": "Add a README.md", "potential_gain": 5})
    if doc_cov < 0.6:
        recs.append({
            "category": "docs",
            "title": f"Add docstrings (coverage {int(doc_cov * 100)}%)",
            "potential_gain": round((1 - doc_cov) * 5, 1),
        })
    if test_pts < 10:
        recs.append({"category": "tests", "title": "Add a tests/ directory with at least one test", "potential_gain": 10})
    if th_cov < 0.7:
        recs.append({
            "category": "types",
            "title": f"Add type hints (coverage {int(th_cov * 100)}%)",
            "potential_gain": round((1 - th_cov) * 10, 1),
        })
    if hyg_pts < 10:
        if not (root / ".gitignore").exists():
            recs.append({"category": "hygiene", "title": "Add a .gitignore", "potential_gain": 3})
        if not any((root / n).exists() for n in ("LICENSE", "LICENSE.md")):
            recs.append({"category": "hygiene", "title": "Add a LICENSE file", "potential_gain": 3})
    if destructive_findings:
        recs.append({
            "category": "security",
            "title": f"Address {len(destructive_findings)} destructive-pattern finding(s)",
            "potential_gain": 15 - destructive_pts,
        })

    recs.sort(key=lambda r: -r.get("potential_gain", 0))

    return {
        "score": total,
        "grade": _grade(total),
        "breakdown": {
            "five_masters": {"pts": ast_pts, "max": 40, "ratio": round(ast_ratio, 3)},
            "destructive": {"pts": round(destructive_pts, 1), "max": 15, "findings": len(destructive_findings)},
            "documentation": {"pts": doc_pts, "max": 10, "has_readme": has_readme, "docstring_coverage": round(doc_cov, 3)},
            "tests": {"pts": test_pts, "max": 10, "present": test_pts > 0},
            "type_hints": {"pts": th_pts, "max": 10, "coverage": round(th_cov, 3)},
            "hygiene": {"pts": hyg_pts, "max": 10},
            "dependencies": {"pts": dep_pts, "max": 5},
        },
        "file_count": len(code_files),
        "file_reports": sorted(file_reports, key=lambda x: x["score"])[:20],
        "top_issues": all_issues[:30],
        "destructive_findings": destructive_findings,
        "recommendations": recs[:10],
    }


def _grade(score: float) -> str:
    if score >= 95: return "S"
    if score >= 90: return "A+"
    if score >= 80: return "A"
    if score >= 70: return "B"
    if score >= 60: return "C"
    if score >= 50: return "D"
    return "F"
