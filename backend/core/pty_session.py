"""PTY-backed interactive shell sessions for the integrated terminal.

Each WebSocket gets a dedicated bash subprocess attached to a real PTY, which fixes:
    - persistent shell state (cd / export / aliases survive between commands)
    - interactive programs (REPLs, pagers, anything that uses isatty())
    - streaming output (every byte is forwarded the moment bash writes it)
    - ANSI control sequences (progress bars, colors, cursor moves — TERM=xterm-256color)
    - long-running commands (no 30s cap; lives as long as the WS stays open)
    - arrow-key history + tab-completion (handled by bash readline directly)

A DEBUG-trap-based destructive guard inside bash refuses obvious foot-guns
(`rm -rf /`, `mkfs`, `dd of=/dev/sd*`, fork-bombs) without needing any
server-side input parsing. J's separate `/api/terminal/exec` HTTP path keeps
the full password-override flow for agent-issued commands.
"""
from __future__ import annotations

import asyncio
import fcntl
import logging
import os
import pty
import signal
import struct
import termios
from pathlib import Path
from typing import Optional

log = logging.getLogger("pty")


BASHRC_CONTENT = r"""
# Gauntlet DevSpace — interactive shell startup
export PS1='\[\e[36m\]// J@sovereign\[\e[0m\] \[\e[37m\]\W\[\e[0m\]\n\[\e[36m\]>\[\e[0m\] '
export PROMPT_COMMAND=''
export TERM=xterm-256color
export PAGER=cat
export EDITOR=true
shopt -s histappend
HISTSIZE=1000
HISTFILESIZE=2000

# --- destructive command refusal trap --------------------------------------
__j_destructive_refuse() {
    # Only fire at top-level interactive depth, never inside our own
    # helper functions (FUNCNAME has only the trap itself at depth 1).
    [[ ${#FUNCNAME[@]} -gt 1 ]] && return 0
    local cmd="$BASH_COMMAND"
    # rm -rf on root / ~ / *
    if [[ "$cmd" =~ rm[[:space:]]+-[rRfF]+[[:space:]]+(/|~|/\*|\.|\.\.)[[:space:]]*$ ]] \
    || [[ "$cmd" =~ rm[[:space:]]+-[rRfF]+[[:space:]]+/[[:space:]] ]] \
    || [[ "$cmd" =~ rm[[:space:]]+--no-preserve-root ]]; then
        printf '\033[31m[INTEGRITY HALT] destructive command refused:\033[0m %s\n' "$cmd" >&2
        printf '\033[33m// use J (the AI panel) with password override for legitimate destructive ops.\033[0m\n' >&2
        return 1
    fi
    # mkfs / dd to a real block device
    if [[ "$cmd" =~ ^mkfs ]] || [[ "$cmd" =~ dd[[:space:]].+of=/dev/(sd|nvme|hd|mmc) ]]; then
        printf '\033[31m[INTEGRITY HALT] block-device write refused:\033[0m %s\n' "$cmd" >&2
        return 1
    fi
    # fork bomb
    if [[ "$cmd" =~ \:\(\)\{[[:space:]]*\:\|\:\& ]]; then
        printf '\033[31m[INTEGRITY HALT] fork bomb refused.\033[0m\n' >&2
        return 1
    fi
    # chmod 777 / chown -R / on system roots
    if [[ "$cmd" =~ chmod[[:space:]]+(-R[[:space:]]+)?777[[:space:]]+/ ]]; then
        printf '\033[31m[INTEGRITY HALT] world-writable on system root refused.\033[0m\n' >&2
        return 1
    fi
    return 0
}
set -o functrace
shopt -s extdebug
trap __j_destructive_refuse DEBUG
# ---------------------------------------------------------------------------

# Welcome line
printf '\033[36m// Gauntlet DevSpace · interactive shell · type `j-help` for the command reference.\033[0m\n'
"""


# Public bashrc = owner bashrc + a second DEBUG trap that hard-refuses
# outbound-network commands. Owner sessions use OWNER_BASHRC; every other
# user gets PUBLIC_BASHRC. Chosen at PTY fork time — nothing the user can
# `export` or `readonly` around from inside the shell.
OWNER_BASHRC = BASHRC_CONTENT  # alias for clarity

PUBLIC_BASHRC = BASHRC_CONTENT.replace(
    "__j_destructive_refuse() {\n    # Only fire at top-level interactive depth, never inside our own\n    # helper functions (FUNCNAME has only the trap itself at depth 1).\n    [[ ${#FUNCNAME[@]} -gt 1 ]] && return 0",
    r"""__j_destructive_refuse() {
    # Only fire at top-level interactive depth, never inside our own
    # helper functions (FUNCNAME has only the trap itself at depth 1).
    [[ ${#FUNCNAME[@]} -gt 1 ]] && return 0
    local cmd_ob="$BASH_COMMAND"
    # --- outbound-network refusal (owner-only wall) ---
    if [[ "$cmd_ob" =~ (^|[[:space:]\;\&\|\`])(curl|wget|nc|ncat|nmap|ssh|scp|sftp|telnet|ftp)([[:space:]]|$) ]]; then
        printf '\033[31m[OWNER-ONLY] outbound-network command refused: %s\033[0m\n' "$cmd_ob" >&2
        printf '\033[33m// this deployment restricts outbound commands to the owner.\033[0m\n' >&2
        return 1
    fi
    if [[ "$cmd_ob" == */dev/tcp/* ]]; then
        printf '\033[31m[OWNER-ONLY] raw TCP socket refused.\033[0m\n' >&2
        return 1
    fi
    if [[ "$cmd_ob" =~ git[[:space:]]+(clone|push|pull|fetch|remote)[[:space:]] ]]; then
        printf '\033[31m[OWNER-ONLY] remote git operation refused: %s\033[0m\n' "$cmd_ob" >&2
        return 1
    fi
    if [[ "$cmd_ob" =~ (pip|pip3)[[:space:]]+install[[:space:]]+(git\+|https?://) ]]; then
        printf '\033[31m[OWNER-ONLY] remote pip install refused.\033[0m\n' >&2
        return 1
    fi""",
)


# The j-help function content (identical for both owner and public shells).
_JHELP_BODY = r"""

j-help() {
    printf '\033[36m== GAUNTLET DEVSPACE TERMINAL ==\033[0m\n\n'
    printf 'Persistent bash inside your project workspace. Real PTY → arrow keys,\n'
    printf 'tab completion, history, REPLs, pagers, and color output all work.\n\n'
    printf '\033[36mScope\033[0m\n'
    printf '  cwd starts at your project root. You can cd anywhere reachable, but\n'
    printf '  the shell dies when you disconnect. Project files survive pod recycle\n'
    printf '  through MongoDB-backed snapshots; /tmp does not.\n\n'
    printf '\033[36mAvailable\033[0m\n'
    printf '  python3 / pip / pipx           node / npm / yarn / npx\n'
    printf '  gcc / g++ / make / cmake       git (full)\n'
    printf '  curl / wget / jq               pytest / ruff / mypy\n'
    printf '  ls / cat / grep / find / sed / awk / head / tail / wc\n'
    printf '  tar / zip / unzip / gzip       ps / top / htop / df / du\n'
    printf '  vim / nano / less / more       tail -f / watch\n\n'
    printf '\033[36mInteractive programs that work\033[0m\n'
    printf '  python3 REPL    node REPL    vim    nano    less    top    htop\n'
    printf '  pytest with progress bars     npm init -y\n\n'
    printf '\033[36mDaemons / long-running\033[0m\n'
    printf '  Foreground (e.g. npm run dev) — fine, lives as long as the tab.\n'
    printf '  Background: append & and redirect (npm run dev > dev.log 2>&1 &).\n'
    printf '  Use jobs / fg %%1 / kill %%1 to manage.\n\n'
    printf '\033[36mWhat the in-shell trap refuses\033[0m\n'
    printf '  Recursive-force delete on root, home, or current dir\n'
    printf '  Block-device writes (mkfs, dd to physical disks)\n'
    printf '  Fork bombs · chmod 777 on system root\n'
    printf '  → For LEGITIMATE destructive ops, ask J in the AI panel — she\n'
    printf '    routes through the password-override flow.\n\n'
    printf '\033[36mPersistence\033[0m\n'
    printf '  Project files: persisted in workspace, restored on reconnect.\n'
    printf '  Installed packages (pip/npm): in workspace, survive disconnect.\n'
    printf '  /tmp and global system state: lost on pod recycle.\n'
}
"""

OWNER_BASHRC = OWNER_BASHRC + _JHELP_BODY
PUBLIC_BASHRC = PUBLIC_BASHRC + _JHELP_BODY


def _ensure_rcfile(is_owner: bool = False) -> str:
    """Write the appropriate bash rcfile, content-addressed so edits
    propagate automatically. Owner and public users get different traps."""
    import hashlib
    content = OWNER_BASHRC if is_owner else PUBLIC_BASHRC
    tag = "owner" if is_owner else "public"
    h = hashlib.sha1(content.encode("utf-8")).hexdigest()[:8]
    p = Path(f"/tmp/j_devspace_bashrc_{tag}_{h}")
    if not p.exists():
        p.write_text(content)
    return str(p)


class PtySession:
    """A single bash subprocess attached to a PTY pair, with async I/O."""

    def __init__(self, cwd: str, env: Optional[dict] = None,
                 is_owner: bool = False):
        self.cwd = cwd
        self.pid: Optional[int] = None
        self.master_fd: int = -1
        self._closed = False
        self._read_task: Optional[asyncio.Task] = None
        self._read_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._env = env or {}
        self._is_owner = bool(is_owner)

    async def start(self) -> None:
        rc = _ensure_rcfile(is_owner=self._is_owner)
        pid, master_fd = pty.fork()
        if pid == 0:
            # Child: exec bash with rcfile
            os.chdir(self.cwd)
            env = {
                **os.environ,
                **self._env,
                "TERM": "xterm-256color",
                "LANG": os.environ.get("LANG", "en_US.UTF-8"),
                "PS1": r"\[\e[36m\]// J@sovereign\[\e[0m\] \[\e[37m\]\W\[\e[0m\]\n\[\e[36m\]>\[\e[0m\] ",
            }
            try:
                os.execvpe("/bin/bash", ["bash", "--noprofile", "--rcfile", rc, "-i"], env)
            except OSError:
                os._exit(127)
            return
        # Parent
        self.pid = pid
        self.master_fd = master_fd
        # non-blocking master so partial reads return immediately
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        # Default size
        self.set_size(80, 24)

        loop = asyncio.get_running_loop()

        def _on_readable():
            if self._closed:
                return
            try:
                chunk = os.read(self.master_fd, 65536)
            except BlockingIOError:
                return
            except OSError:
                self._closed = True
                try:
                    loop.remove_reader(self.master_fd)
                except (ValueError, OSError):
                    pass
                self._read_queue.put_nowait(b"")
                return
            if not chunk:
                self._closed = True
                try:
                    loop.remove_reader(self.master_fd)
                except (ValueError, OSError):
                    pass
                self._read_queue.put_nowait(b"")
                return
            self._read_queue.put_nowait(chunk)

        loop.add_reader(master_fd, _on_readable)

    async def read(self) -> bytes:
        return await self._read_queue.get()

    def write(self, data: bytes) -> None:
        if self._closed or self.master_fd < 0:
            return
        try:
            os.write(self.master_fd, data)
        except OSError:
            self._closed = True

    def set_size(self, cols: int, rows: int) -> None:
        if self.master_fd < 0:
            return
        try:
            fcntl.ioctl(
                self.master_fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, cols, 0, 0),
            )
        except OSError:
            pass

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        loop = asyncio.get_event_loop()
        try:
            loop.remove_reader(self.master_fd)
        except (ValueError, OSError, RuntimeError):
            pass
        if self.pid:
            try:
                os.kill(self.pid, signal.SIGHUP)
            except ProcessLookupError:
                pass
            try:
                os.waitpid(self.pid, os.WNOHANG)
            except ChildProcessError:
                pass
        if self.master_fd >= 0:
            try:
                os.close(self.master_fd)
            except OSError:
                pass
        self.master_fd = -1

    @property
    def closed(self) -> bool:
        return self._closed
