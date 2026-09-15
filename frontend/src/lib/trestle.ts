import type { Finding } from "./api";

export const TRESTLE_ADDRESS_FIELD_ORDER = [
  "location_type",
  "street_line_1",
  "street_line_2",
  "city",
  "postal_code",
  "zip4",
  "state_code",
  "country_code",
  "lat_long",
  "accuracy",
  "delivery_point",
  "link_to_person_start_date",
] as const;

export const TRESTLE_OWNER_FIELD_ORDER = [
  "age_range",
  "gender",
  "type",
  "link_to_phone_start_date",
  "industry",
] as const;

export const ADDRESS_FIELD_LABELS: Record<string, string> = {
  street_line_1: "Street address",
  street_line_2: "Address line 2",
  city: "City",
  postal_code: "ZIP / Postal code",
  zip: "ZIP / Postal code",
  zip4: "ZIP+4",
  state_code: "State",
  country_code: "Country",
  location_type: "Location type",
  delivery_point: "Delivery point",
  lat_long: "Coordinates",
  latitude: "Latitude",
  longitude: "Longitude",
  accuracy: "Accuracy",
  link_to_person_start_date: "Linked since",
};

const OWNER_FIELD_LABELS: Record<string, string> = {
  age_range: "Age range",
  gender: "Gender",
  type: "Type",
  link_to_phone_start_date: "Linked to phone",
  industry: "Industry",
};

const ID_VALUE_RE = /^(Location|Person|Business)\.[A-Za-z0-9._-]+$/i;

export type TrestleOwnerGroup = {
  ownerIndex: number;
  name: string;
  nameFinding: Finding | null;
  ownerFields: Record<string, unknown>;
  ownerType: string;
  alternateNames: string[];
  addresses: Finding[];
};

function extraOf(finding: Finding): Record<string, unknown> {
  return finding.extra && typeof finding.extra === "object" ? finding.extra : {};
}

export function isTrestleFinding(finding: Finding): boolean {
  return extraOf(finding).source === "trestle";
}

export function isTrestleAddressFinding(finding: Finding): boolean {
  if (!isTrestleFinding(finding)) return false;
  if (extraOf(finding).finding_type === "trestle_address") return true;
  const title = (finding.title || "").trim().toLowerCase();
  return title === "current address" || title === "address" || title.endsWith(" address");
}

export function isTrestleOwnerFinding(finding: Finding): boolean {
  if (!isTrestleFinding(finding)) return false;
  if (extraOf(finding).finding_type === "trestle_owner") return true;
  const title = (finding.title || "").trim().toLowerCase();
  return title === "name" || title === "owner";
}

export function isTrestleOwnerFieldFinding(finding: Finding): boolean {
  if (!isTrestleFinding(finding)) return false;
  if (finding.kind === "email") return false;
  if (extraOf(finding).finding_type === "trestle_owner_field") return true;
  const title = (finding.title || "").trim().toLowerCase();
  return title === "alternate name";
}

export function isTrestleGroupedFinding(finding: Finding): boolean {
  return (
    isTrestleAddressFinding(finding) ||
    isTrestleOwnerFinding(finding) ||
    isTrestleOwnerFieldFinding(finding)
  );
}

export function isTrestleCurrentAddress(finding: Finding): boolean {
  return extraOf(finding).is_current === true;
}

function ownerIndexOf(finding: Finding, fallback: number): number {
  const raw = extraOf(finding).owner_index;
  return typeof raw === "number" ? raw : fallback;
}

function asOwnerFields(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

export function ownerDisplayFields(fields: Record<string, unknown>): { key: string; label: string; value: string }[] {
  const seen = new Set<string>();
  const rows: { key: string; label: string; value: string }[] = [];
  for (const key of TRESTLE_OWNER_FIELD_ORDER) {
    if (!(key in fields)) continue;
    const value = formatTrestleField(fields[key]);
    if (!value || isHiddenId(key, value)) continue;
    seen.add(key);
    rows.push({ key, label: OWNER_FIELD_LABELS[key] || friendlyFieldLabel(key), value });
  }
  for (const [key, raw] of Object.entries(fields)) {
    if (seen.has(key)) continue;
    if (["name", "firstname", "middlename", "lastname", "alternate_names"].includes(key)) continue;
    const value = formatTrestleField(raw);
    if (!value || isHiddenId(key, value)) continue;
    rows.push({ key, label: OWNER_FIELD_LABELS[key] || friendlyFieldLabel(key), value });
  }
  return rows;
}

export function addressDisplayFields(fields: Record<string, unknown>): { key: string; label: string; value: string }[] {
  const seen = new Set<string>();
  const rows: { key: string; label: string; value: string }[] = [];

  const coords = coordinateValue(fields);
  const push = (key: string, value: string) => {
    if (!value || isHiddenId(key, value) || seen.has(key)) return;
    seen.add(key);
    rows.push({ key, label: ADDRESS_FIELD_LABELS[key] || friendlyFieldLabel(key), value });
  };

  for (const key of TRESTLE_ADDRESS_FIELD_ORDER) {
    if (key === "lat_long") {
      if (coords) push("lat_long", coords);
      continue;
    }
    if (key === "postal_code") {
      const postal = formatTrestleField(fields.postal_code ?? fields.zip);
      if (postal) push("postal_code", postal);
      continue;
    }
    if (!(key in fields)) continue;
    push(key, formatTrestleField(fields[key]));
  }

  for (const [key, raw] of Object.entries(fields)) {
    if (seen.has(key)) continue;
    if (["id", "zip", "latitude", "longitude"].includes(key)) continue;
    if (key === "lat_long" && coords) continue;
    const value = formatTrestleField(raw);
    if (!value || isHiddenId(key, value)) continue;
    push(key, value);
  }
  return rows;
}

function coordinateValue(fields: Record<string, unknown>): string {
  if (fields.lat_long != null) return formatTrestleField(fields.lat_long);
  if (fields.latitude != null || fields.longitude != null) {
    return formatTrestleField({
      latitude: fields.latitude,
      longitude: fields.longitude,
      accuracy: fields.accuracy,
    });
  }
  return "";
}

function isHiddenId(key: string, value: string): boolean {
  if (key === "id" || key.endsWith("_id")) return true;
  return ID_VALUE_RE.test(value.trim());
}

function friendlyFieldLabel(key: string): string {
  return key.replaceAll("_", " ").replace(/\b\w/g, (ch) => ch.toUpperCase());
}

export function formatTrestleField(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) {
    return value.map(formatTrestleField).filter(Boolean).join(", ");
  }
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>;
    if ("latitude" in rec || "longitude" in rec) {
      const coords = [rec.latitude, rec.longitude]
        .filter((part) => part != null && part !== "")
        .map((part) => String(part))
        .join(", ");
      const accuracy = rec.accuracy != null && rec.accuracy !== "" ? String(rec.accuracy) : "";
      if (coords && accuracy) return `${coords} (${accuracy})`;
      return coords || accuracy;
    }
    return Object.entries(rec)
      .filter(([, part]) => part != null && part !== "")
      .map(([key, part]) => `${key}: ${formatTrestleField(part)}`)
      .filter((part) => !part.endsWith(": "))
      .join(" · ");
  }
  return String(value);
}

export function groupTrestlePhoneFindings(items: Finding[]): {
  owners: TrestleOwnerGroup[];
  leftover: Finding[];
} {
  const leftover: Finding[] = [];
  const groups = new Map<number, TrestleOwnerGroup>();
  let autoIndex = 0;

  const ensure = (index: number): TrestleOwnerGroup => {
    let group = groups.get(index);
    if (!group) {
      group = {
        ownerIndex: index,
        name: "",
        nameFinding: null,
        ownerFields: {},
        ownerType: "",
        alternateNames: [],
        addresses: [],
      };
      groups.set(index, group);
    }
    return group;
  };

  for (const finding of items) {
    if (!isTrestleGroupedFinding(finding)) {
      leftover.push(finding);
      continue;
    }
    const index = ownerIndexOf(finding, autoIndex);
    autoIndex = Math.max(autoIndex, index + 1);
    const group = ensure(index);
    if (isTrestleOwnerFinding(finding)) {
      group.nameFinding = finding;
      group.name = finding.value;
      const fields = asOwnerFields(extraOf(finding).owner);
      if (Object.keys(fields).length) group.ownerFields = fields;
      group.ownerType = ownerTypeOf(group, extraOf(finding));
      continue;
    }
    if (isTrestleAddressFinding(finding)) {
      group.addresses.push(finding);
      if (!group.name) {
        const ownerName = extraOf(finding).owner_name;
        if (typeof ownerName === "string" && ownerName.trim()) group.name = ownerName.trim();
      }
      continue;
    }
    if ((finding.title || "").trim().toLowerCase() === "alternate name" && finding.value) {
      group.alternateNames.push(finding.value);
    }
  }

  const owners = [...groups.values()]
    .filter((group) => group.nameFinding || group.addresses.length)
    .sort((a, b) => a.ownerIndex - b.ownerIndex)
    .map((group) => ({
      ...group,
      ownerType: group.ownerType || ownerTypeOf(group, extraOf(group.nameFinding || group.addresses[0])),
      addresses: [...group.addresses].sort((a, b) => {
        const currentDelta = Number(isTrestleCurrentAddress(b)) - Number(isTrestleCurrentAddress(a));
        if (currentDelta) return currentDelta;
        return 0;
      }),
    }));

  return { owners, leftover };
}

function ownerTypeOf(group: TrestleOwnerGroup, extra: Record<string, unknown>): string {
  const fromFields = formatTrestleField(group.ownerFields.type);
  if (fromFields) return fromFields;
  if (typeof extra.owner_type === "string" && extra.owner_type.trim()) return extra.owner_type.trim();
  return "";
}

export function isPersonOwner(owner: TrestleOwnerGroup): boolean {
  const type = owner.ownerType.trim().toLowerCase();
  if (type === "person") return true;
  if (isBusinessOwner(owner)) return false;
  return Boolean(owner.ownerFields.age_range || owner.ownerFields.gender);
}

export function isBusinessOwner(owner: TrestleOwnerGroup): boolean {
  const type = owner.ownerType.trim().toLowerCase();
  return type === "business" || type === "company" || type === "organization";
}

export function ownersForDisplay(owners: TrestleOwnerGroup[]): TrestleOwnerGroup[] {
  if (owners.some(isPersonOwner)) return owners.filter((owner) => !isBusinessOwner(owner));
  return owners;
}
