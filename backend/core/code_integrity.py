"""Code Integrity Gateway — deterministic pre-write validation.

This module sits between J's `write_file` / `create_file` tool calls and the
actual disk write. EVERY content payload passes through `validate()`. If the
result is `ok=False`, the write is rejected and the error is returned to J as
a structured tool result so she can correct herself in the SAME turn — no user
token cost, no human in the loop, no truncated files reaching disk.

Design tenets:
1. LLMs drift. The gate must not. ALL checks here are pure-function, AST-level,
   or pattern-matched — zero LLM calls.
2. Reject is better than accept-with-warning. We never write a file that fails.
3. Errors must be actionable — they tell J exactly WHERE the file broke and
   what to do next (continue from line N, close brace at column M, etc.).
4. Language-aware. Generic structural checks for unknown languages.

This is the framework upgrade beyond Five Masters (which audits AFTER write):
together they form a two-tier deterministic system.
    Tier 1 (this module): pre-write — does this content even compile / parse?
    Tier 2 (Five Masters): post-write — is this content GOOD?
J cannot reach Tier 2 if Tier 1 rejects her.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Optional


# Patterns that scream "the LLM gave up partway through" or hallucinated a
# fake completion. ANY match rejects the write.
TRUNCATION_PATTERNS = [
    # Bare ellipsis used as a placeholder (NOT a real `...` Ellipsis literal,
    # which would parse fine in Python). We look for ellipsis in COMMENTS or
    # standalone lines, with optional descriptive suffix.
    re.compile(r"^\s*(#|//|/\*|<!--)\s*\.\.\.\s*(rest|remaining|continued|truncated|omitted|elided|skip|more|content|code|implementation|impl|todo|file|function|class)\b",
               re.IGNORECASE | re.MULTILINE),
    # Lone ellipsis comment with nothing else: `# ...` or `// ...` or `<!-- ... -->`
    re.compile(r"^\s*(#|//)\s*\.\.\.\s*(\*/)?\s*$", re.MULTILINE),
    re.compile(r"^\s*<!--\s*\.\.\.\s*-->\s*$", re.MULTILINE),
    # Explicit truncation hints
    re.compile(r"^\s*(#|//|/\*|<!--)\s*(rest of (?:the )?(?:file|code|implementation|content)|previous (?:code|content) (?:remains|unchanged)|content (?:omitted|truncated|elided|continues)|unchanged from (?:above|before)|same as (?:before|above))",
               re.IGNORECASE | re.MULTILINE),
    # Placeholder comments
    re.compile(r"<\s*(TRUNCATED|REST OF CODE|REST OF FILE|YOUR CODE HERE|CONTINUE HERE|\.\.\.)\s*>",
               re.IGNORECASE),
    # Block comments asking for completion later
    re.compile(r"/\*\s*(TODO:?\s*)?(complete|finish|fill in|continue|expand)\s+(this|the)\s+(file|implementation|function|class)",
               re.IGNORECASE),
]


@dataclass
class ValidationResult:
    ok: bool
    language: str
    error: str = ""
    line: Optional[int] = None
    column: Optional[int] = None
    detail: dict = field(default_factory=dict)
    # Hint J can use directly when fixing on retry
    hint: str = ""

    def as_tool_error(self) -> dict:
        """Shape suitable for returning as a tool result so J retries."""
        return {
            "error": self.error,
            "code_integrity": {
                "language": self.language,
                "line": self.line,
                "column": self.column,
                "hint": self.hint,
                **self.detail,
            },
        }


def detect_language(path: str) -> str:
    p = (path or "").lower()
    if p.endswith(".py") or p.endswith(".pyi"):
        return "python"
    if p.endswith(".json"):
        return "json"
    if p.endswith(".yaml") or p.endswith(".yml"):
        return "yaml"
    if p.endswith((".js", ".jsx", ".mjs", ".cjs")):
        return "javascript"
    if p.endswith((".ts", ".tsx")):
        return "typescript"
    if p.endswith(".html") or p.endswith(".htm"):
        return "html"
    if p.endswith(".css") or p.endswith(".scss") or p.endswith(".less"):
        return "css"
    if p.endswith(".md") or p.endswith(".markdown"):
        return "markdown"
    return "text"


# ---- Truncation detector ----

def check_truncation(content: str) -> Optional[tuple[int, str]]:
    """Return (line_number, matched_text) of the first truncation marker found,
    or None if clean.
    """
    for pattern in TRUNCATION_PATTERNS:
        m = pattern.search(content)
        if m:
            line = content[:m.start()].count("\n") + 1
            return line, m.group(0).strip()[:120]
    return None


# ---- Balance checker (generic, for unknown languages and a sanity check) ----

PAIRS = {"(": ")", "[": "]", "{": "}"}
CLOSERS = {")", "]", "}"}


def check_balance(content: str, language: str) -> Optional[tuple[int, str]]:
    """Verify braces/brackets/parens balance, ignoring string + comment bodies.

    Returns (line_number, error_message) or None if balanced.
    Markdown, html, css get a relaxed check (skipped — those don't balance
    structurally like code).
    """
    if language in {"markdown", "html", "css", "text", "yaml"}:
        return None
    stack: list[tuple[str, int, int]] = []  # (opener, line, col)
    in_str: Optional[str] = None  # '"' / "'" / '`' or None
    in_line_comment = False
    in_block_comment = False
    line, col = 1, 0
    i, n = 0, len(content)
    while i < n:
        ch = content[i]
        nxt = content[i + 1] if i + 1 < n else ""
        col += 1
        if ch == "\n":
            line += 1
            col = 0
            in_line_comment = False
            i += 1
            continue
        if in_line_comment:
            i += 1
            continue
        if in_block_comment:
            if ch == "*" and nxt == "/":
                in_block_comment = False
                i += 2
                col += 1
                continue
            i += 1
            continue
        if in_str:
            if ch == "\\":  # escape next
                i += 2
                col += 1
                continue
            if ch == in_str:
                in_str = None
            i += 1
            continue
        # Not in string/comment now
        if ch == "#" and language == "python":
            in_line_comment = True
            i += 1
            continue
        if ch == "/" and nxt == "/" and language in {"javascript", "typescript", "css"}:
            in_line_comment = True
            i += 2
            col += 1
            continue
        if ch == "/" and nxt == "*" and language in {"javascript", "typescript", "css"}:
            in_block_comment = True
            i += 2
            col += 1
            continue
        if ch in ('"', "'", "`"):
            # Python triple-quote — skip the whole thing
            if ch in ('"', "'") and content[i:i + 3] in ('"""', "'''") and language == "python":
                close = content[i:i + 3]
                end = content.find(close, i + 3)
                if end == -1:
                    return line, f"unterminated triple-quoted string starting at line {line}"
                # count newlines we crossed
                line += content[i:end].count("\n")
                i = end + 3
                continue
            in_str = ch
            i += 1
            continue
        if ch in PAIRS:
            stack.append((ch, line, col))
        elif ch in CLOSERS:
            if not stack:
                return line, f"unexpected '{ch}' at line {line} col {col} — no matching opener"
            opener, ol, oc = stack.pop()
            if PAIRS[opener] != ch:
                return line, f"mismatched '{ch}' at line {line} col {col} — expected '{PAIRS[opener]}' to close '{opener}' opened at line {ol} col {oc}"
        i += 1

    if in_str:
        return line, f"unterminated string literal (opened with {in_str}) — reached EOF still inside string"
    if in_block_comment:
        return line, "unterminated /* */ block comment — reached EOF"
    if stack:
        opener, ol, oc = stack[-1]
        return ol, f"unclosed '{opener}' opened at line {ol} col {oc} — file ends without matching '{PAIRS[opener]}'"
    return None


# ---- EOF completeness ----

def check_eof_completeness(content: str, language: str) -> Optional[str]:
    """Catch obvious 'file ends mid-thought' cases."""
    if not content:
        return "file is empty"
    # Markup / prose languages legitimately end with '>' (e.g. `</html>`) or
    # other punctuation the cliff-ending heuristic below would flag. Skip the
    # cliff check for those — truncation-marker patterns still apply.
    if language in {"html", "markdown", "text", "css", "yaml"}:
        return None
    # Trailing newline is expected for source files (POSIX), warn if missing
    last_line = content.rstrip().split("\n")[-1] if content.rstrip() else ""
    # Common 'cliff' endings
    cliff_endings = (
        ",", "+", "-", "*", "/", "=", "<", ">", "&", "|", "%", "^",
        "(", "[", "{", "&&", "||", "==", "!=", "<=", ">=",
    )
    stripped = last_line.rstrip()
    if stripped and stripped.endswith(cliff_endings) and not stripped.startswith(("#", "//", "/*")):
        return f"file ends mid-expression with '{stripped[-3:]}' — likely truncated"
    return None


# ---- Per-language deep parse ----

def parse_python(content: str) -> Optional[tuple[int, str]]:
    try:
        ast.parse(content)
        return None
    except SyntaxError as e:
        return (e.lineno or 1, f"SyntaxError: {e.msg}")
    except ValueError as e:
        return (1, f"parse error: {e}")


def parse_json(content: str) -> Optional[tuple[int, str]]:
    try:
        json.loads(content)
        return None
    except json.JSONDecodeError as e:
        return (e.lineno, f"JSONDecodeError: {e.msg}")


# ---- Main entrypoint ----

def validate(path: str, content: str) -> ValidationResult:
    """Run the full gate. Cheap (microseconds). Returns ValidationResult."""
    language = detect_language(path)

    # 1. Truncation markers — fastest reject, highest signal
    trunc = check_truncation(content)
    if trunc:
        line, match = trunc
        return ValidationResult(
            ok=False, language=language, line=line,
            error="Truncation marker detected — write rejected.",
            detail={"matched": match},
            hint=("Found a placeholder comment indicating an incomplete file. "
                  "Re-emit the FULL file content without `...`, 'rest of code', "
                  "or similar placeholders. The disk has no prior version to "
                  "interleave with — you must write the entire file in one shot, "
                  "or use append_file for large files."),
        )

    # 2. Language-aware deep parse
    if language == "python":
        err = parse_python(content)
        if err:
            return ValidationResult(
                ok=False, language=language, line=err[0],
                error=err[1],
                hint=("Python AST parse failed. Re-read the file with read_file, "
                      "then re-emit with the syntax error fixed. If the file is too "
                      "long to write in one go, use append_file to add chunks."),
            )
    elif language == "json":
        err = parse_json(content)
        if err:
            return ValidationResult(
                ok=False, language=language, line=err[0],
                error=err[1],
                hint="JSON is invalid. Fix the structural error and re-emit.",
            )

    # 3. Brace / bracket / quote balance (catches truncation in JS/TS/C-like)
    bal = check_balance(content, language)
    if bal:
        line, msg = bal
        return ValidationResult(
            ok=False, language=language, line=line,
            error=msg,
            hint=("Structural delimiters don't balance. Most often: the file was "
                  "cut off before the final brace. Re-emit the COMPLETE file."),
        )

    # 4. EOF cliff check
    eof = check_eof_completeness(content, language)
    if eof:
        return ValidationResult(
            ok=False, language=language,
            error=eof,
            hint="The file ends mid-expression. Re-emit with the closing tokens.",
        )

    return ValidationResult(ok=True, language=language)
