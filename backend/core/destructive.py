# Destructive-code detection. Hard-block patterns.
"""Detects destructive code patterns that require password-guarded override."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class DestructiveMatch:
    pattern: str
    line: int
    snippet: str
    severity: str  # "critical" | "high"
    reason: str


# Patterns that must HARD BLOCK without password override.
DESTRUCTIVE_PATTERNS: list[tuple[str, str, str, str]] = [
    # (regex, severity, name, reason)
    (r"\brm\s+-rf\s+(/|~|\$HOME|\*)", "critical", "rm -rf root",
     "Recursive force-delete of root/home/wildcard"),
    (r":\(\)\{\s*:\|:&\s*\};:", "critical", "fork bomb", "Classic fork bomb"),
    (r"\bmkfs\.[a-z0-9]+", "critical", "mkfs", "Filesystem format command"),
    (r"\bdd\s+if=.*of=/dev/", "critical", "dd to device",
     "Raw device write - drive destruction"),
    (r">\s*/dev/sd[a-z]", "critical", "device redirect",
     "Writing to raw block device"),
    (r"\bshutdown\b|\breboot\b|\bhalt\b|\binit\s+0", "high", "system shutdown",
     "Host shutdown/reboot command"),
    (r"\bchmod\s+-R\s+777\s+/", "critical", "chmod 777 root",
     "World-writable root filesystem"),
    (r"\bchown\s+-R\s+.*\s+/(\s|$)", "high", "chown root",
     "Recursive ownership change of root"),
    (r"DROP\s+(DATABASE|TABLE|SCHEMA)\s+", "high", "drop database/table",
     "Destructive SQL DDL"),
    (r"TRUNCATE\s+TABLE\s+", "high", "truncate", "SQL truncate - data loss"),
    (r"DELETE\s+FROM\s+\w+\s*(;|$)", "high", "unfiltered DELETE",
     "Unfiltered DELETE - drops all rows"),
    (r"os\.system\(['\"](rm|del|format|shutdown)", "high", "os.system destructive",
     "Python os.system invoking destructive shell"),
    (r"subprocess\.(run|call|Popen)\(\s*\[?['\"](rm|del|format|shutdown)",
     "high", "subprocess destructive",
     "Python subprocess invoking destructive command"),
    (r"shutil\.rmtree\((['\"](/|~)|Path\(['\"](/|~))", "critical", "shutil.rmtree root",
     "Python tree-delete starting at root/home"),
    (r"git\s+push\s+.*--force\s+.*\s+main\b", "high", "force push to main",
     "Force-pushing to main branch"),
    (r"git\s+reset\s+--hard\s+HEAD~", "high", "git reset --hard",
     "Hard reset rewriting history"),
    (r"\.\s*drop_database\s*\(", "critical", "mongo drop_database",
     "MongoDB drop_database call"),
    (r"\beval\s*\(\s*request\.", "high", "eval on request input",
     "eval() of user-supplied input (RCE)"),
    (r"\bexec\s*\(\s*request\.", "high", "exec on request input",
     "exec() of user-supplied input (RCE)"),
]


def scan(code: str) -> list[DestructiveMatch]:
    """Scan a string for destructive patterns. Returns matches."""
    matches: list[DestructiveMatch] = []
    lines = code.split("\n")
    for i, line in enumerate(lines, 1):
        for pattern, severity, name, reason in DESTRUCTIVE_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                matches.append(DestructiveMatch(
                    pattern=name,
                    line=i,
                    snippet=line.strip()[:200],
                    severity=severity,
                    reason=reason,
                ))
    return matches


def scan_command(cmd: str) -> list[DestructiveMatch]:
    """Scan a terminal command string."""
    return scan(cmd)
