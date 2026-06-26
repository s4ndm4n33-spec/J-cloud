import { useMemo, useState } from "react";
import { MagnifyingGlass, BookOpen, Copy } from "@phosphor-icons/react";

/**
 * Curated command glossary for the integrated terminal. Static list — these
 * are the binaries actually confirmed present in the runtime container (see
 * /app/backend/core/terminal_reference.md). One-line descriptions + a single
 * concrete usage example each. Searchable across name, description, example.
 *
 * Not every flag of every tool — the user can run `<cmd> --help` in the
 * terminal for full surface. This is the discoverable surface.
 */
const GLOSSARY = [
  // --- File system ---
  { name: "ls",     cat: "file", desc: "List directory contents.",                                  ex: "ls -la" },
  { name: "cd",     cat: "file", desc: "Change directory. State persists in the interactive shell.", ex: "cd src" },
  { name: "pwd",    cat: "file", desc: "Print current working directory.",                          ex: "pwd" },
  { name: "cat",    cat: "file", desc: "Print file contents to stdout.",                            ex: "cat README.md" },
  { name: "head",   cat: "file", desc: "Print the first N lines of a file (default 10).",           ex: "head -n 20 server.py" },
  { name: "tail",   cat: "file", desc: "Print last N lines, or follow a growing log with -f.",      ex: "tail -f app.log" },
  { name: "find",   cat: "file", desc: "Recursive file search by name, type, size, modtime.",       ex: 'find . -name "*.py" -type f' },
  { name: "grep",   cat: "file", desc: "Search file contents for a pattern (use -r for recursive).", ex: 'grep -rn "TODO" src/' },
  { name: "sed",    cat: "file", desc: "Stream editor — in-place text substitution.",               ex: 'sed -i "s/foo/bar/g" file.txt' },
  { name: "awk",    cat: "file", desc: "Pattern-scanning + processing language for tabular text.",  ex: 'awk \'{print $1, $3}\' data.tsv' },
  { name: "wc",     cat: "file", desc: "Word/line/byte count.",                                     ex: "wc -l *.py" },
  { name: "mv",     cat: "file", desc: "Move or rename a file/directory.",                          ex: "mv old.txt new.txt" },
  { name: "cp",     cat: "file", desc: "Copy a file or directory (-r for recursive).",              ex: "cp -r src/ backup/" },
  { name: "rm",     cat: "file", desc: "Remove file. Use -rf for recursive. BLOCKED on system roots.", ex: "rm tmp.txt" },
  { name: "mkdir",  cat: "file", desc: "Create directory. -p creates parents as needed.",            ex: "mkdir -p src/utils" },
  { name: "touch",  cat: "file", desc: "Create empty file or update mtime.",                        ex: "touch newfile.js" },
  { name: "chmod",  cat: "file", desc: "Change file permissions (777 on system roots BLOCKED).",    ex: "chmod +x script.sh" },

  // --- Compression ---
  { name: "tar",    cat: "compress", desc: "Archive directories. -czf to create, -xzf to extract.",  ex: "tar -czf out.tar.gz src/" },
  { name: "zip",    cat: "compress", desc: "Create a .zip archive.",                                ex: "zip -r out.zip src/" },
  { name: "unzip",  cat: "compress", desc: "Extract a .zip archive.",                               ex: "unzip out.zip -d ./" },
  { name: "gzip",   cat: "compress", desc: "Compress a single file to .gz.",                        ex: "gzip data.csv" },

  // --- Python ---
  { name: "python3",cat: "python", desc: "Python 3.11+ interpreter / REPL (interactive works here).", ex: "python3 script.py" },
  { name: "pip",    cat: "python", desc: "Python package installer.",                               ex: "pip install requests" },
  { name: "pipx",   cat: "python", desc: "Install Python apps in isolated venvs.",                  ex: "pipx install black" },
  { name: "pytest", cat: "python", desc: "Test runner with auto-discovery.",                        ex: "pytest -q tests/" },
  { name: "ruff",   cat: "python", desc: "Fast Python linter + formatter.",                         ex: "ruff check . --fix" },
  { name: "mypy",   cat: "python", desc: "Static type checker.",                                    ex: "mypy server.py" },

  // --- Node ---
  { name: "node",   cat: "node", desc: "Node 20.x interpreter / REPL.",                             ex: "node index.js" },
  { name: "npm",    cat: "node", desc: "Node package manager.",                                     ex: "npm install" },
  { name: "yarn",   cat: "node", desc: "Alternative Node package manager (preferred in this app).", ex: "yarn add react" },
  { name: "npx",    cat: "node", desc: "Run a Node package without installing globally.",           ex: "npx create-react-app demo" },

  // --- Build / native ---
  { name: "gcc",    cat: "build", desc: "GNU C compiler.",                                          ex: "gcc -O2 hello.c -o hello" },
  { name: "g++",    cat: "build", desc: "GNU C++ compiler.",                                        ex: "g++ -std=c++17 main.cpp -o app" },
  { name: "make",   cat: "build", desc: "Run a Makefile target.",                                   ex: "make test" },
  { name: "cmake",  cat: "build", desc: "Cross-platform build system generator.",                   ex: "cmake -S . -B build && cmake --build build" },

  // --- Git ---
  { name: "git",    cat: "git", desc: "Git version control (clone falls back to dulwich on prod).", ex: "git status" },
  { name: "git log", cat: "git", desc: "Show commit history.",                                       ex: "git log --oneline -20" },
  { name: "git diff", cat: "git", desc: "Show unstaged changes.",                                    ex: "git diff" },
  { name: "git commit", cat: "git", desc: "Snapshot staged changes.",                                ex: 'git add . && git commit -m "msg"' },

  // --- Network ---
  { name: "curl",   cat: "net", desc: "HTTP/HTTPS client.",                                         ex: "curl -s https://api.github.com/zen" },
  { name: "wget",   cat: "net", desc: "Non-interactive file downloader.",                           ex: "wget https://example.com/file.tar.gz" },
  { name: "jq",     cat: "net", desc: "Streaming JSON processor.",                                  ex: 'curl -s api.example.com/x | jq .name' },

  // --- Interactive ---
  { name: "vim",    cat: "interactive", desc: "Modal text editor. Works in the PTY shell.",         ex: "vim notes.md" },
  { name: "nano",   cat: "interactive", desc: "Simpler text editor. Easier to exit than vim.",      ex: "nano notes.md" },
  { name: "less",   cat: "interactive", desc: "Page through long output. `q` to quit.",             ex: "git log | less" },
  { name: "top",    cat: "interactive", desc: "Live process viewer. `q` to quit.",                  ex: "top" },
  { name: "htop",   cat: "interactive", desc: "Friendlier top. Arrow keys to scroll, F10 to quit.", ex: "htop" },

  // --- System ---
  { name: "ps",     cat: "system", desc: "Snapshot of running processes.",                          ex: "ps -ef | grep python" },
  { name: "df",     cat: "system", desc: "Disk free, by mount point.",                              ex: "df -h" },
  { name: "du",     cat: "system", desc: "Disk usage, recursive. -sh for summary.",                 ex: "du -sh node_modules/" },
  { name: "free",   cat: "system", desc: "Memory usage snapshot.",                                  ex: "free -h" },
  { name: "uptime", cat: "system", desc: "How long the pod has been up + load average.",            ex: "uptime" },
  { name: "env",    cat: "system", desc: "Print all environment variables.",                        ex: "env | grep PATH" },
  { name: "which",  cat: "system", desc: "Print the path of an executable on PATH.",                ex: "which python3" },

  // --- Shell built-ins useful in our PTY ---
  { name: "j-help",  cat: "j",     desc: "Print the Gauntlet DevSpace terminal reference card.",     ex: "j-help" },
  { name: "export",  cat: "j",     desc: "Set an env var that PERSISTS for the rest of this shell.", ex: "export DEBUG=1" },
  { name: "alias",   cat: "j",     desc: "Define a shorthand. Persists for this shell session.",     ex: 'alias ll="ls -la"' },
  { name: "jobs",    cat: "j",     desc: "List background jobs you started with `&`.",               ex: "jobs" },
  { name: "fg",      cat: "j",     desc: "Bring a background job back to the foreground.",           ex: "fg %1" },
];

const CATEGORIES = [
  { key: "all",         label: "ALL" },
  { key: "file",        label: "FILE" },
  { key: "compress",    label: "ZIP/TAR" },
  { key: "python",      label: "PYTHON" },
  { key: "node",        label: "NODE" },
  { key: "build",       label: "BUILD" },
  { key: "git",         label: "GIT" },
  { key: "net",         label: "NETWORK" },
  { key: "interactive", label: "TUI" },
  { key: "system",      label: "SYSTEM" },
  { key: "j",           label: "J / SHELL" },
];

export default function GlossaryPanel() {
  const [query, setQuery] = useState("");
  const [cat, setCat] = useState("all");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return GLOSSARY.filter((c) => {
      if (cat !== "all" && c.cat !== cat) return false;
      if (!q) return true;
      return (
        c.name.toLowerCase().includes(q) ||
        c.desc.toLowerCase().includes(q) ||
        c.ex.toLowerCase().includes(q)
      );
    });
  }, [query, cat]);

  function copyExample(ex) {
    try { navigator.clipboard?.writeText(ex); } catch { /* ignore */ }
  }

  return (
    <div className="h-full flex flex-col" data-testid="glossary-panel">
      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-2">
        <BookOpen size={12} className="text-cyan" weight="fill" />
        <span className="font-display text-[0.65rem] tracking-[0.25em] text-cyan">COMMAND GLOSSARY</span>
        <span className="ml-auto font-mono text-[0.6rem] text-alloy">{filtered.length}/{GLOSSARY.length}</span>
      </div>

      <div className="px-3 py-2 border-b border-cyan/10 flex items-center gap-2">
        <MagnifyingGlass size={11} className="text-alloy" />
        <input
          type="text"
          placeholder="search by name, description, or example…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="flex-1 bg-midnight border border-cyan/20 px-2 py-1 font-mono text-[0.7rem] text-gridwhite"
          data-testid="glossary-search"
        />
      </div>

      <div className="px-2 py-1.5 border-b border-cyan/10 flex flex-wrap gap-1">
        {CATEGORIES.map((c) => (
          <button
            key={c.key}
            onClick={() => setCat(c.key)}
            className={`font-mono text-[0.6rem] px-1.5 py-0.5 border ${
              cat === c.key
                ? "border-cyan text-cyan bg-cyan/10"
                : "border-cyan/20 text-alloy hover:text-cyan"
            }`}
            data-testid={`glossary-cat-${c.key}`}
          >{c.label}</button>
        ))}
      </div>

      <div className="flex-1 overflow-auto scrollbar-thin">
        {filtered.length === 0 ? (
          <div className="p-4 font-mono text-[0.7rem] text-alloy text-center">
            // no matches. Try clearing the filter or category.
          </div>
        ) : (
          filtered.map((c) => (
            <div
              key={c.name}
              className="px-3 py-2 border-b border-cyan/5 hover:bg-cyan/5"
              data-testid={`glossary-cmd-${c.name.replace(/\s/g, "-")}`}
            >
              <div className="flex items-baseline gap-2">
                <code className="font-mono text-[0.78rem] text-cyan">{c.name}</code>
                <span className="font-mono text-[0.55rem] text-alloy/60 uppercase tracking-widest">{c.cat}</span>
              </div>
              <div className="font-mono text-[0.7rem] text-gridwhite/90 mt-1">{c.desc}</div>
              <div className="mt-1 flex items-center gap-2 group">
                <code className="font-mono text-[0.7rem] text-orange/90 bg-steel border border-cyan/10 px-1.5 py-0.5 flex-1 overflow-x-auto scrollbar-thin whitespace-pre">
                  {c.ex}
                </code>
                <button
                  onClick={() => copyExample(c.ex)}
                  title="Copy example"
                  className="text-alloy hover:text-cyan opacity-0 group-hover:opacity-100"
                  data-testid={`glossary-copy-${c.name.replace(/\s/g, "-")}`}
                >
                  <Copy size={11} />
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <div className="px-3 py-1.5 border-t border-cyan/10 font-mono text-[0.6rem] text-alloy/70">
        {`> for full flags, run `}
        <span className="text-cyan">{`<command> --help`}</span>
        {` in the terminal.`}
      </div>
    </div>
  );
}
