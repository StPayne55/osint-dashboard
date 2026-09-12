import type { Finding } from "./api";

const PHOTO_KEYS = new Set([
  "image",
  "avatar",
  "photo",
  "photos",
  "picture",
  "pictures",
  "profile_image",
  "profileimage",
  "profile_photo",
  "gravatar",
  "thumbnail",
  "thumbnailurl",
  "thumbnail_url",
  "photo_url",
  "avatar_url",
  "image_url",
  "picture_url",
]);

const NEST_KEYS = new Set(["ids", "identity", "profile"]);
const URLISH_KEYS = ["url", "value", "src", "href", "image", "avatar", "photo"];
const BLOCKED_HOSTS = new Set(["localhost", "127.0.0.1", "0.0.0.0", "::1"]);
const MAX_PHOTOS = 24;

export type PhotoItem = {
  title: string;
  url: string;
  source?: string;
};

export function normalizePhotoUrl(raw?: string | null): string | null {
  if (!raw) return null;
  let text = raw.trim();
  if (!text || /^(data:|javascript:|file:|about:)/i.test(text)) return null;
  if (text.startsWith("//")) text = `https:${text}`;
  try {
    const parsed = new URL(text);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return null;
    const host = (parsed.hostname || "").toLowerCase();
    if (!host || BLOCKED_HOSTS.has(host) || host.endsWith(".onion") || host.endsWith(".local")) {
      return null;
    }
    if (parsed.username || parsed.password) return null;
    parsed.protocol = "https:";
    parsed.hash = "";
    const href = parsed.toString();
    return href.length > 2000 ? null : href;
  } catch {
    return null;
  }
}

export function photoDedupeKey(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.hostname.toLowerCase();
    const path = parsed.pathname.replace(/\/$/, "").toLowerCase();
    if (host.endsWith("gravatar.com") && path.includes("/avatar/")) {
      return `gravatar:${path.split("/").pop() || ""}`;
    }
    return `${host}${path}`;
  } catch {
    return url.replace(/\/$/, "").toLowerCase();
  }
}

function iterPhotoUrls(value: unknown, depth = 0): string[] {
  if (depth > 3 || value == null) return [];
  if (typeof value === "string") {
    const url = normalizePhotoUrl(value);
    return url ? [url] : [];
  }
  if (Array.isArray(value)) {
    return value.slice(0, 12).flatMap((item) => iterPhotoUrls(item, depth + 1));
  }
  if (typeof value === "object") {
    const rec = value as Record<string, unknown>;
    return URLISH_KEYS.flatMap((key) => (key in rec ? iterPhotoUrls(rec[key], depth + 1) : []));
  }
  return [];
}

export function photosFromExtra(extra?: Record<string, unknown> | null): string[] {
  if (!extra) return [];
  const found: string[] = [];
  const seen = new Set<string>();
  const walk = (data: Record<string, unknown>) => {
    for (const [key, value] of Object.entries(data)) {
      const lowered = key.toLowerCase();
      if (PHOTO_KEYS.has(lowered)) {
        for (const url of iterPhotoUrls(value)) {
          const dedupe = photoDedupeKey(url);
          if (seen.has(dedupe)) continue;
          seen.add(dedupe);
          found.push(url);
        }
      } else if (NEST_KEYS.has(lowered) && value && typeof value === "object" && !Array.isArray(value)) {
        walk(value as Record<string, unknown>);
      }
    }
  };
  walk(extra);
  return found;
}

export function collectPhotoFindings(findings: Finding[]): PhotoItem[] {
  const seen = new Set<string>();
  const out: PhotoItem[] = [];

  const add = (title: string, url: string, source?: string) => {
    const normalized = normalizePhotoUrl(url);
    if (!normalized) return;
    const key = photoDedupeKey(normalized);
    if (seen.has(key) || out.length >= MAX_PHOTOS) return;
    seen.add(key);
    out.push({ title: title || "Photo", url: normalized, source });
  };

  for (const finding of findings) {
    if (finding.kind !== "image") continue;
    const source = typeof finding.extra?.source === "string" ? finding.extra.source : undefined;
    add(finding.title || "Photo", finding.url || finding.value, source);
  }
  for (const finding of findings) {
    const extras = photosFromExtra(finding.extra);
    if (!extras.length) continue;
    const source =
      (typeof finding.extra?.source === "string" && finding.extra.source) ||
      (typeof finding.extra?.site === "string" && finding.extra.site) ||
      undefined;
    let title = finding.title || "Photo";
    if (finding.kind !== "image" && title && !/(photo|photos|avatar|image)$/i.test(title)) {
      title = `${title} photo`;
    }
    for (const url of extras) add(title, url, source);
  }
  return out;
}

export function isImageDork(finding: Finding): boolean {
  if (finding.kind !== "link") return false;
  if (finding.extra?.tab === "images") return true;
  return /google images/i.test(finding.title || "");
}
