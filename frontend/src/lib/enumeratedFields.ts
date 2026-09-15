import type { Finding } from "./api";

const ENUMERATED_LABELS: Record<string, string> = {
  candidate: "Candidates",
  candidates: "Candidates",
  "alternate name": "Aliases",
  "alternate names": "Aliases",
  alias: "Aliases",
  aliases: "Aliases",
};

export type EnumeratedFindingGroup =
  | { type: "single"; finding: Finding }
  | { type: "enumerated"; label: string; findings: Finding[] };

export function enumeratedGroupLabel(title: string | null | undefined): string | null {
  const key = (title || "").trim().toLowerCase();
  return ENUMERATED_LABELS[key] ?? null;
}

export function isEnumeratedFieldTitle(title: string | null | undefined): boolean {
  return enumeratedGroupLabel(title) != null;
}

/** Collapse consecutive candidate / alias rows so the UI can show one shared header. */
export function groupEnumeratedFindings(items: Finding[]): EnumeratedFindingGroup[] {
  const groups: EnumeratedFindingGroup[] = [];
  for (const finding of items) {
    const label = enumeratedGroupLabel(finding.title);
    const last = groups[groups.length - 1];
    if (label && last?.type === "enumerated" && last.label === label) {
      last.findings.push(finding);
      continue;
    }
    if (label) {
      groups.push({ type: "enumerated", label, findings: [finding] });
      continue;
    }
    groups.push({ type: "single", finding });
  }
  return groups;
}
