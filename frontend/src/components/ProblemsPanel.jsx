export default function ProblemsPanel({ issues, language }) {
  if (!issues?.length) {
    return (
      <div className="p-3 font-mono text-xs text-alloy h-full" data-testid="problems-panel">
        // no problems detected · run GAUNTLET → QUICK AST to evaluate
      </div>
    );
  }
  return (
    <div className="p-2 font-mono text-xs h-full overflow-auto scrollbar-thin" data-testid="problems-panel">
      <div className="text-alloy mb-2">// {issues.length} issue(s) · {language}</div>
      {issues.map((iss, i) => (
        <div key={i} className="flex gap-2 py-0.5">
          <span className="text-cyan w-10">L{iss.line}</span>
          <span
            className="w-24"
            style={{ color: iss.severity === "error" ? "var(--orange)" : "var(--alloy-gray)" }}
          >[{iss.master}]</span>
          <span className="text-gridwhite/85 flex-1">{iss.message}</span>
        </div>
      ))}
    </div>
  );
}
