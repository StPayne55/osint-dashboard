import type { Finding } from "./api";

export type SocialBadgeItem = {
  key: string;
  site: string;
  slug: string;
  url?: string | null;
};

const CONFIRMED_HIT_RE =
  /appears registered|email registered|is taken(?:\b|$)|associated on|claimed|username is taken/i;

const UNCONFIRMED_RE =
  /not installed|none claimed|ignorant checked|unavailable|rate[- ]limit|error|failed|no (public )?(hits?|caller name)/i;

const NON_SOCIAL_TITLES = new Set([
  "site checks",
  "caller name (cnam)",
  "caller name",
  "validity",
  "about",
  "mx lookup",
  "source note",
  "time zones",
  "time zone",
]);

const SITE_ALIASES: Record<string, { name: string; slug: string }> = {
  x: { name: "X", slug: "x" },
  twitter: { name: "X", slug: "x" },
  "twitter.com": { name: "X", slug: "x" },
  "x.com": { name: "X", slug: "x" },
  instagram: { name: "Instagram", slug: "instagram" },
  "instagram.com": { name: "Instagram", slug: "instagram" },
  github: { name: "GitHub", slug: "github" },
  "github.com": { name: "GitHub", slug: "github" },
  gitlab: { name: "GitLab", slug: "gitlab" },
  "gitlab.com": { name: "GitLab", slug: "gitlab" },
  bitbucket: { name: "Bitbucket", slug: "bitbucket" },
  "bitbucket.org": { name: "Bitbucket", slug: "bitbucket" },
  spotify: { name: "Spotify", slug: "spotify" },
  "spotify.com": { name: "Spotify", slug: "spotify" },
  "open.spotify.com": { name: "Spotify", slug: "spotify" },
  facebook: { name: "Facebook", slug: "facebook" },
  "facebook.com": { name: "Facebook", slug: "facebook" },
  linkedin: { name: "LinkedIn", slug: "linkedin" },
  "linkedin.com": { name: "LinkedIn", slug: "linkedin" },
  tiktok: { name: "TikTok", slug: "tiktok" },
  "tiktok.com": { name: "TikTok", slug: "tiktok" },
  youtube: { name: "YouTube", slug: "youtube" },
  "youtube.com": { name: "YouTube", slug: "youtube" },
  reddit: { name: "Reddit", slug: "reddit" },
  "reddit.com": { name: "Reddit", slug: "reddit" },
  snapchat: { name: "Snapchat", slug: "snapchat" },
  "snapchat.com": { name: "Snapchat", slug: "snapchat" },
  telegram: { name: "Telegram", slug: "telegram" },
  "t.me": { name: "Telegram", slug: "telegram" },
  "telegram.me": { name: "Telegram", slug: "telegram" },
  discord: { name: "Discord", slug: "discord" },
  "discord.com": { name: "Discord", slug: "discord" },
  twitch: { name: "Twitch", slug: "twitch" },
  "twitch.tv": { name: "Twitch", slug: "twitch" },
  pinterest: { name: "Pinterest", slug: "pinterest" },
  "pinterest.com": { name: "Pinterest", slug: "pinterest" },
  tumblr: { name: "Tumblr", slug: "tumblr" },
  "tumblr.com": { name: "Tumblr", slug: "tumblr" },
  medium: { name: "Medium", slug: "medium" },
  "medium.com": { name: "Medium", slug: "medium" },
  steam: { name: "Steam", slug: "steam" },
  "steamcommunity.com": { name: "Steam", slug: "steam" },
  soundcloud: { name: "SoundCloud", slug: "soundcloud" },
  "soundcloud.com": { name: "SoundCloud", slug: "soundcloud" },
  threads: { name: "Threads", slug: "threads" },
  "threads.net": { name: "Threads", slug: "threads" },
  bluesky: { name: "Bluesky", slug: "bluesky" },
  bsky: { name: "Bluesky", slug: "bluesky" },
  "bsky.app": { name: "Bluesky", slug: "bluesky" },
  mastodon: { name: "Mastodon", slug: "mastodon" },
  "mastodon.social": { name: "Mastodon", slug: "mastodon" },
  wikipedia: { name: "Wikipedia", slug: "wikipedia" },
  "wikipedia.org": { name: "Wikipedia", slug: "wikipedia" },
  "en.wikipedia.org": { name: "Wikipedia", slug: "wikipedia" },
  keybase: { name: "Keybase", slug: "keybase" },
  "keybase.io": { name: "Keybase", slug: "keybase" },
  patreon: { name: "Patreon", slug: "patreon" },
  "patreon.com": { name: "Patreon", slug: "patreon" },
  flickr: { name: "Flickr", slug: "flickr" },
  "flickr.com": { name: "Flickr", slug: "flickr" },
  behance: { name: "Behance", slug: "behance" },
  "behance.net": { name: "Behance", slug: "behance" },
  dribbble: { name: "Dribbble", slug: "dribbble" },
  "dribbble.com": { name: "Dribbble", slug: "dribbble" },
  wordpress: { name: "WordPress", slug: "wordpress" },
  "wordpress.com": { name: "WordPress", slug: "wordpress" },
  vk: { name: "VK", slug: "vk" },
  vkontakte: { name: "VK", slug: "vk" },
  "vk.com": { name: "VK", slug: "vk" },
  npm: { name: "npm", slug: "npm" },
  "npmjs.com": { name: "npm", slug: "npm" },
  docker: { name: "Docker Hub", slug: "docker" },
  "hub.docker.com": { name: "Docker Hub", slug: "docker" },
  leetcode: { name: "LeetCode", slug: "leetcode" },
  "leetcode.com": { name: "LeetCode", slug: "leetcode" },
  hackerrank: { name: "HackerRank", slug: "hackerrank" },
  "hackerrank.com": { name: "HackerRank", slug: "hackerrank" },
  kaggle: { name: "Kaggle", slug: "kaggle" },
  "kaggle.com": { name: "Kaggle", slug: "kaggle" },
  goodreads: { name: "Goodreads", slug: "goodreads" },
  "goodreads.com": { name: "Goodreads", slug: "goodreads" },
  letterboxd: { name: "Letterboxd", slug: "letterboxd" },
  "letterboxd.com": { name: "Letterboxd", slug: "letterboxd" },
  chess: { name: "Chess.com", slug: "chess" },
  "chess.com": { name: "Chess.com", slug: "chess" },
  roblox: { name: "Roblox", slug: "roblox" },
  "roblox.com": { name: "Roblox", slug: "roblox" },
  quora: { name: "Quora", slug: "quora" },
  "quora.com": { name: "Quora", slug: "quora" },
  slideshare: { name: "SlideShare", slug: "slideshare" },
  "slideshare.net": { name: "SlideShare", slug: "slideshare" },
  aboutme: { name: "About.me", slug: "aboutme" },
  "about.me": { name: "About.me", slug: "aboutme" },
  devto: { name: "Dev.to", slug: "devto" },
  "dev.to": { name: "Dev.to", slug: "devto" },
  hackernews: { name: "Hacker News", slug: "hackernews" },
  "news.ycombinator.com": { name: "Hacker News", slug: "hackernews" },
  lastfm: { name: "Last.fm", slug: "lastfm" },
  "last.fm": { name: "Last.fm", slug: "lastfm" },
  producthunt: { name: "Product Hunt", slug: "producthunt" },
  "producthunt.com": { name: "Product Hunt", slug: "producthunt" },
  replit: { name: "Replit", slug: "replit" },
  "replit.com": { name: "Replit", slug: "replit" },
  codepen: { name: "CodePen", slug: "codepen" },
  "codepen.io": { name: "CodePen", slug: "codepen" },
  gravatar: { name: "Gravatar", slug: "gravatar" },
  "gravatar.com": { name: "Gravatar", slug: "gravatar" },
};

const KNOWN_ICON_SLUGS = new Set(Object.values(SITE_ALIASES).map((site) => site.slug));

/** Homepage of a registrable domain (https://instagram.com/) is not a profile. */
export function isConcreteProfileUrl(url?: string | null): boolean {
  if (!url) return false;
  try {
    const parsed = new URL(url.includes("://") ? url : `https://${url}`);
    if (parsed.protocol !== "http:" && parsed.protocol !== "https:") return false;
    const parts = parsed.pathname.split("/").filter(Boolean);
    if (parts.length === 0) return false;
    const home = new Set(["home", "index", "index.html", "index.htm", "login", "signup", "register", "about", "www"]);
    if (parts.length === 1 && home.has(parts[0].toLowerCase())) return false;
    return true;
  } catch {
    return false;
  }
}

export function hasKnownSocialIcon(slug: string): boolean {
  return KNOWN_ICON_SLUGS.has(slug);
}

export function isConfirmedSocialFinding(finding: Finding): boolean {
  if (finding.kind === "profile" && isConcreteProfileUrl(finding.url || finding.value)) return true;
  if (finding.kind !== "note") return false;
  const title = (finding.title || "").trim().toLowerCase();
  const value = finding.value || "";
  if (NON_SOCIAL_TITLES.has(title)) return false;
  if (UNCONFIRMED_RE.test(title) || UNCONFIRMED_RE.test(value)) return false;
  if (CONFIRMED_HIT_RE.test(value)) return true;
  const extra = finding.extra && typeof finding.extra === "object" ? finding.extra : {};
  const status = typeof extra.status === "string" ? extra.status : "";
  return /claimed|found/i.test(status);
}

export function collectConfirmedSocials(findings: Finding[]): SocialBadgeItem[] {
  const bySlug = new Map<string, SocialBadgeItem>();
  for (const finding of findings) {
    if (!isConfirmedSocialFinding(finding)) continue;
    const site = resolveSocialSite(finding);
    if (!site) continue;
    const url = pickSocialUrl(finding);
    const existing = bySlug.get(site.slug);
    if (!existing) {
      bySlug.set(site.slug, {
        key: site.slug,
        site: site.name,
        slug: site.slug,
        url,
      });
      continue;
    }
    if (!existing.url && url) existing.url = url;
    if (site.name.length > existing.site.length) existing.site = site.name;
  }
  return [...bySlug.values()].sort((a, b) => a.site.localeCompare(b.site));
}

export function resolveSocialSite(finding: Finding): { name: string; slug: string } | null {
  const extra = finding.extra && typeof finding.extra === "object" ? finding.extra : {};
  const url = pickSocialUrl(finding) || (typeof finding.url === "string" ? finding.url : "") || "";
  const host = hostnameOf(url);
  const domain = typeof extra.domain === "string" ? extra.domain : "";
  const title = stripSiteDecor(finding.title || "");
  const candidates = [host, domain, title, siteFromValue(finding.value || "")];
  for (const raw of candidates) {
    const alias = lookupSiteAlias(raw);
    if (alias) return alias;
  }
  if (title && !NON_SOCIAL_TITLES.has(title.toLowerCase())) {
    return { name: title, slug: slugFromLabel(title) };
  }
  if (host) {
    const name = host.replace(/^www\./, "").split(".")[0] || host;
    return { name, slug: slugFromLabel(name) };
  }
  return null;
}

function pickSocialUrl(finding: Finding): string | null {
  const extra = finding.extra && typeof finding.extra === "object" ? finding.extra : {};
  const candidates = [finding.url, finding.kind === "profile" ? finding.value : "", extra.link, extra.url];
  for (const raw of candidates) {
    if (typeof raw !== "string") continue;
    if (isConcreteProfileUrl(raw)) return raw.includes("://") ? raw : `https://${raw}`;
  }
  return null;
}

function siteFromValue(value: string): string {
  const registered = value.match(/(?:registered|associated) on\s+([^\s(]+)/i);
  if (registered?.[1]) return registered[1].replace(/[.,;:)]+$/, "");
  const taken = value.match(/taken on\s+([^\s(]+)/i);
  if (taken?.[1]) return taken[1].replace(/[.,;:)]+$/, "");
  return "";
}

function hostnameOf(url: string): string {
  if (!url) return "";
  try {
    return new URL(url.includes("://") ? url : `https://${url}`).hostname.toLowerCase();
  } catch {
    return "";
  }
}

function stripSiteDecor(title: string): string {
  return title.replace(/\s*\(.*?\)\s*/g, " ").replace(/\s+/g, " ").trim();
}

function lookupSiteAlias(raw: string): { name: string; slug: string } | null {
  const key = normalizeSiteKey(raw);
  if (!key) return null;
  if (SITE_ALIASES[key]) return SITE_ALIASES[key];
  const noTld = key.replace(/\.(com|net|org|io|tv|me|app|social)$/g, "");
  if (noTld !== key && SITE_ALIASES[noTld]) return SITE_ALIASES[noTld];
  for (const [alias, site] of Object.entries(SITE_ALIASES)) {
    if (alias.includes(".") && (key === alias || key.endsWith(`.${alias}`))) return site;
  }
  return null;
}

function normalizeSiteKey(raw: string): string {
  return raw
    .trim()
    .toLowerCase()
    .replace(/^https?:\/\//, "")
    .replace(/^www\./, "")
    .replace(/\/.*$/, "")
    .replace(/[^a-z0-9.]+/g, "");
}

function slugFromLabel(label: string): string {
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "")
    .slice(0, 24);
  return slug || "site";
}
