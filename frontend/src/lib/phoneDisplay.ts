import type { Finding, Query, Report } from "./api";

export const EMPTY_CNAM_DISPLAY = "No Caller Name Resolved";

export const PHONE_SCANNER_IDS = ["phone", "numverify", "twilio", "whitepages", "trestle"] as const;

const PHONE_NUMBER_TITLES = new Set([
  "e.164",
  "twilio e.164",
  "national format",
  "formatted",
  "number",
  "local format",
  "international format",
  "international",
]);

const SITE_NOTE_RE =
  /appears registered|not a profile url|ignorant (not installed|checked)/i;

const EMPTY_CNAM_RE =
  /no caller name on file|cnam (was empty|often blank)|common for mobile/i;

const GENERIC_LINE_TYPES = new Set(["fixed or mobile", "unknown", ""]);

const SOURCE_RANK: Record<string, number> = {
  trestle: 5,
  twilio: 4,
  whitepages: 3,
  numverify: 2,
  phone: 1,
};

export type PhoneFormatInput = {
  e164?: string | null;
  national?: string | null;
  countryCode?: string | null;
  raw?: string | null;
};

export function digitsOnly(value: string | null | undefined): string {
  return (value || "").replace(/\D/g, "");
}

export function formatPhoneNumber(input: PhoneFormatInput): string {
  const country = digitsOnly(input.countryCode);
  const national = digitsOnly(input.national);
  if (country && national) {
    return formatFromParts(country, national);
  }

  const e164 = asE164(input.e164) || asE164(input.raw);
  if (e164) {
    const parsed = splitE164(e164, country);
    if (parsed) return formatFromParts(parsed.country, parsed.national);
    return e164;
  }

  const raw = (input.raw || "").trim();
  const rawDigits = digitsOnly(raw);
  if (rawDigits.length === 10) return formatFromParts("1", rawDigits);
  if (rawDigits.length === 11 && rawDigits.startsWith("1")) {
    return formatFromParts("1", rawDigits.slice(1));
  }
  if (rawDigits.length >= 8) return `+${rawDigits}`;
  return raw;
}

export function resolvePhoneFormatInput(
  query?: Query | null,
  identity?: Report["identity"] | null,
  findings?: Record<string, Finding[]>,
): PhoneFormatInput {
  const fromFindings = findings ? firstPhoneFindingValue(findings) : "";
  return {
    e164: query?.phone_e164 || identity?.phones?.[0] || fromFindings || null,
    national: query?.phone_national || null,
    countryCode: query?.phone_country_code || null,
    raw: query?.raw || fromFindings || null,
  };
}

export function hasResolvedPhone(
  query?: Query | null,
  identity?: Report["identity"] | null,
  findings?: Record<string, Finding[]>,
): boolean {
  if (query?.type === "phone") return true;
  if (query?.phone_e164) return true;
  if (identity?.phones && identity.phones.length > 0) return true;
  if (!findings) return false;
  if (PHONE_SCANNER_IDS.some((id) => (findings[id] || []).length > 0)) return true;
  return Object.values(findings).some((rows) => rows.some((f) => f.kind === "phone" && Boolean(f.value)));
}

export function pickHeroName(...names: Array<string | null | undefined>): string {
  const candidates = names
    .map((name) => (name || "").trim())
    .filter((name) => name && !isEmptyCnamValue(name));
  if (!candidates.length) return "";
  return [...candidates].sort((a, b) => comparePersonNames(b, a))[0];
}

export function scorePersonName(name: string): number {
  const tokens = nameTokens(name);
  const letters = name.replace(/[^A-Za-z]/g, "");
  const allCaps = letters.length > 0 && letters === letters.toUpperCase();
  let score = tokens.length * 12 + name.length;
  if (!allCaps) score += 10;
  if (tokens.length >= 3) score += 16;
  return score;
}

function nameTokens(name: string): string[] {
  return name
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter(Boolean);
}

function comparePersonNames(a: string, b: string): number {
  const aTokens = nameTokens(a);
  const bTokens = nameTokens(b);
  const aHasB = bTokens.every((token) => aTokens.includes(token));
  const bHasA = aTokens.every((token) => bTokens.includes(token));
  if (aHasB !== bHasA) return aHasB ? 1 : -1;
  if (aHasB && bHasA && aTokens.length !== bTokens.length) return aTokens.length - bTokens.length;
  return scorePersonName(a) - scorePersonName(b);
}

export function friendlyCnamValue(value: string | null | undefined): string {
  const text = (value || "").trim();
  if (!text || EMPTY_CNAM_RE.test(text)) return EMPTY_CNAM_DISPLAY;
  return text;
}

export function isEmptyCnamValue(value: string | null | undefined): boolean {
  return friendlyCnamValue(value) === EMPTY_CNAM_DISPLAY;
}

export function curatePhoneCardFindings(items: Finding[], formatted: string): Finding[] {
  const rows: Finding[] = [];
  if (formatted) {
    rows.push({ kind: "phone", title: "Formatted", value: formatted });
  }

  const cnam = pickCnam(items);
  if (cnam) rows.push(cnam);

  const region = pickFirstTitle(items, ["region", "location"]);
  if (region) rows.push(cleanRow(region, "Region"));

  const country = pickCountry(items);
  if (country) rows.push(cleanRow(country, "Country"));

  const lineType = pickBestLineType(items);
  if (lineType) rows.push(cleanRow(lineType, "Line type"));

  const carrier = pickBestCarrier(items);
  if (carrier) rows.push(cleanRow(carrier, "Carrier"));

  return rows;
}

export function pickBestLineType(items: Finding[]): Finding | null {
  return pickBest(items, (f) => titleOf(f) === "line type", scoreLineType);
}

export function pickBestCarrier(items: Finding[]): Finding | null {
  return pickBest(
    items,
    (f) => {
      const title = titleOf(f);
      return title === "carrier" || title === "carrier (dataset)";
    },
    scoreCarrier,
  );
}

function pickCnam(items: Finding[]): Finding | null {
  const matches = items.filter((f) => {
    const title = titleOf(f);
    return title === "caller name (cnam)" || title === "caller name";
  });
  if (!matches.length) return null;
  const named = matches.find((f) => f.kind === "metadata" && f.value && !isEmptyCnamValue(f.value) && !/error/i.test(f.value));
  const chosen = named || matches[0];
  const value = /error/i.test(chosen.value) && !isEmptyCnamValue(chosen.value)
    ? chosen.value
    : friendlyCnamValue(chosen.value);
  return {
    kind: named ? "metadata" : chosen.kind,
    title: "Caller name (CNAM)",
    value,
  };
}

function pickCountry(items: Finding[]): Finding | null {
  return (
    pickFirstTitle(items, ["country"]) ||
    pickFirstTitle(items, ["country name"]) ||
    pickFirstTitle(items, ["country code"])
  );
}

function pickFirstTitle(items: Finding[], titles: string[]): Finding | null {
  const wanted = new Set(titles);
  return items.find((f) => wanted.has(titleOf(f)) && f.value.trim()) || null;
}

function pickBest(
  items: Finding[],
  match: (f: Finding) => boolean,
  score: (f: Finding) => number,
): Finding | null {
  const candidates = items.filter((f) => match(f) && f.value.trim());
  if (!candidates.length) return null;
  return [...candidates].sort((a, b) => score(b) - score(a))[0];
}

function scoreLineType(finding: Finding): number {
  const generic = GENERIC_LINE_TYPES.has(finding.value.trim().toLowerCase()) ? 0 : 20;
  return sourceRank(finding) * 10 + generic + Math.min(finding.value.length, 12);
}

function scoreCarrier(finding: Finding): number {
  const datasetPenalty = titleOf(finding) === "carrier (dataset)" ? -4 : 0;
  return sourceRank(finding) * 10 + datasetPenalty + Math.min(finding.value.length, 24);
}

function sourceRank(finding: Finding): number {
  const extra = finding.extra && typeof finding.extra === "object" ? finding.extra : {};
  const source = typeof extra.source === "string" ? extra.source.toLowerCase() : "";
  if (source && SOURCE_RANK[source]) return SOURCE_RANK[source];
  if (titleOf(finding).includes("dataset")) return SOURCE_RANK.phone;
  return 0;
}

function cleanRow(finding: Finding, title: string): Finding {
  return { kind: finding.kind, title, value: finding.value };
}

function titleOf(finding: Finding): string {
  return (finding.title || "").trim().toLowerCase();
}

export function isPhoneCardClutter(finding: Finding): boolean {
  const title = titleOf(finding);
  if (PHONE_NUMBER_TITLES.has(title)) return true;
  if (SITE_NOTE_RE.test(finding.value) || SITE_NOTE_RE.test(finding.title || "")) return true;
  if (
    title === "validity" ||
    title === "time zones" ||
    title === "time zone" ||
    title === "prepaid" ||
    title === "commercial" ||
    title === "caller type" ||
    title === "line type intelligence" ||
    title === "site checks" ||
    title === "site registration"
  ) {
    return true;
  }
  return false;
}

function firstPhoneFindingValue(findings: Record<string, Finding[]>): string {
  for (const rows of Object.values(findings)) {
    for (const finding of rows) {
      if (finding.kind === "phone" && finding.value) return finding.value;
    }
  }
  return "";
}

function asE164(value: string | null | undefined): string | null {
  if (!value) return null;
  const trimmed = value.trim();
  if (/^\+\d{8,15}$/.test(trimmed)) return trimmed;
  const digits = digitsOnly(trimmed);
  if (digits.length === 11 && digits.startsWith("1")) return `+${digits}`;
  if (digits.length === 10) return `+1${digits}`;
  if (trimmed.startsWith("+") && digits.length >= 8 && digits.length <= 15) return `+${digits}`;
  return null;
}

function splitE164(e164: string, knownCountry?: string): { country: string; national: string } | null {
  const digits = digitsOnly(e164);
  if (knownCountry && digits.startsWith(knownCountry) && digits.length > knownCountry.length) {
    return { country: knownCountry, national: digits.slice(knownCountry.length) };
  }
  if (digits.length === 11 && digits.startsWith("1")) {
    return { country: "1", national: digits.slice(1) };
  }
  if (digits.length === 10) {
    return { country: "1", national: digits };
  }
  return null;
}

function formatFromParts(country: string, national: string): string {
  if (country === "1" && national.length === 10) {
    return `+1 ${national.slice(0, 3)}-${national.slice(3, 6)}-${national.slice(6)}`;
  }
  if (national.length >= 6) {
    const grouped = [national.slice(0, 3), national.slice(3, 6), national.slice(6)].filter(Boolean);
    return `+${country} ${grouped.join(" ")}`;
  }
  return `+${country} ${national}`.trim();
}
