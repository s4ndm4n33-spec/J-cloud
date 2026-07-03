"""Unit tests for Code Integrity Gateway — HTML/SVG regression.

Regression: `check_eof_completeness` used to flag any file ending in `>` (i.e.
every HTML file, since they end with `</html>`) as "mid-expression truncated",
which blocked J from ever writing a valid HTML/SVG diagram.

These tests ensure:
  1. Valid HTML files pass the gate.
  2. Valid SVG-in-HTML passes.
  3. Truncation markers still get rejected inside HTML.
  4. Python cliff-ending regression still fires (guard didn't over-relax).
"""
from __future__ import annotations

from backend.core.code_integrity import validate


VALID_HTML = """<!DOCTYPE html>
<html lang=\"en\">
<head><meta charset=\"utf-8\"><title>Nissan Versa Door Lock</title></head>
<body>
  <h1>Door Lock Diagram</h1>
  <svg viewBox=\"0 0 200 200\" xmlns=\"http://www.w3.org/2000/svg\">
    <rect x=\"10\" y=\"10\" width=\"180\" height=\"180\" fill=\"none\" stroke=\"black\"/>
    <circle cx=\"100\" cy=\"100\" r=\"40\" fill=\"steelblue\"/>
    <text x=\"100\" y=\"105\" text-anchor=\"middle\" fill=\"white\">LOCK</text>
  </svg>
</body>
</html>
"""


def test_valid_html_passes():
    r = validate("diagram.html", VALID_HTML)
    assert r.ok, f"Valid HTML rejected: {r.error} @ line {r.line}"
    assert r.language == "html"


def test_valid_html_ending_no_newline():
    """Even without trailing newline (ends flush with `>`), should pass."""
    r = validate("index.html", "<html><body><p>Hi</p></body></html>")
    assert r.ok, f"Rejected minimal HTML: {r.error}"


def test_html_truncation_marker_still_rejected():
    bad = (
        "<!DOCTYPE html>\n<html><body>\n"
        "<!-- rest of file unchanged -->\n"
        "</body></html>\n"
    )
    r = validate("bad.html", bad)
    assert not r.ok
    assert "Truncation marker" in r.error


def test_python_cliff_still_fires():
    """Guard: we relaxed HTML/markdown only — Python truncation still caught."""
    bad_py = "def foo():\n    return 1 +\n"
    r = validate("bad.py", bad_py)
    assert not r.ok


def test_markdown_ending_with_gt_passes():
    md = "# Title\n\n> Quoted line at EOF\n"
    r = validate("notes.md", md)
    assert r.ok


def test_empty_html_rejected():
    r = validate("empty.html", "")
    assert not r.ok
    assert "empty" in r.error.lower()
