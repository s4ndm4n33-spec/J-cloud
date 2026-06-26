import { Folder, GitBranch, ShieldCheck, BookOpen } from "@phosphor-icons/react";

const ITEMS = [
  { key: "files", label: "Files", Icon: Folder },
  { key: "git", label: "Git", Icon: GitBranch },
  { key: "gauntlet", label: "Gauntlet", Icon: ShieldCheck },
  { key: "glossary", label: "Command Glossary", Icon: BookOpen },
];

export default function LeftRail({ active, onChange }) {
  return (
    <div className="w-12 border-r border-cyan/10 bg-midnight flex flex-col items-center py-2 gap-1" data-testid="left-rail">
      {ITEMS.map(({ key, label, Icon }) => (
        <button
          key={key}
          data-testid={`rail-${key}`}
          title={label}
          onClick={() => onChange(key)}
          className={`h-10 w-10 flex items-center justify-center transition-colors relative ${
            active === key ? "text-cyan" : "text-alloy hover:text-gridwhite"
          }`}
        >
          {active === key && (
            <span className="absolute left-0 top-1 bottom-1 w-[2px] bg-cyan"></span>
          )}
          <Icon size={18} weight={active === key ? "fill" : "regular"} />
        </button>
      ))}
    </div>
  );
}
