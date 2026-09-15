import assert from "node:assert/strict";
import type { Finding } from "../src/lib/api.ts";
import {
  collectConfirmedSocials,
  isConcreteProfileUrl,
  isConfirmedSocialFinding,
  resolveSocialSite,
} from "../src/lib/socials.ts";

function finding(partial: Partial<Finding> & Pick<Finding, "kind" | "title" | "value">): Finding {
  return { ...partial };
}

assert.equal(isConcreteProfileUrl("https://instagram.com/"), false);
assert.equal(isConcreteProfileUrl("https://instagram.com/stpayne55"), true);
assert.equal(isConcreteProfileUrl("https://github.com/torvalds"), true);

const sherlock = finding({
  kind: "profile",
  title: "GitHub",
  value: "https://github.com/stpayne55",
  url: "https://github.com/stpayne55",
});
const maigret = finding({
  kind: "profile",
  title: "Spotify",
  value: "https://open.spotify.com/user/stpayne55",
  url: "https://open.spotify.com/user/stpayne55",
});
const holehe = finding({
  kind: "note",
  title: "instagram",
  value: "Email registered on instagram.com",
  extra: { domain: "instagram.com" },
});
const socialscan = finding({
  kind: "note",
  title: "Twitter",
  value: "stpayne55 is taken on Twitter (registration, not a profile URL)",
});
const ignorant = finding({
  kind: "note",
  title: "snapchat",
  value: "Number appears registered on snapchat.com (not a profile URL)",
  extra: { domain: "snapchat.com" },
});
const emptyCnam = finding({
  kind: "note",
  title: "Caller name (CNAM)",
  value: "No caller name on file (common for mobile numbers — CNAM often blank).",
});
const ignorantMiss = finding({
  kind: "note",
  title: "Site checks",
  value: "ignorant checked 4 site(s); none claimed this number",
});
const notInstalled = finding({
  kind: "note",
  title: "Site checks",
  value: "ignorant not installed — metadata only",
});
const mx = finding({
  kind: "note",
  title: "MX lookup",
  value: "gmail.com MX ok",
});
const homepageProfile = finding({
  kind: "profile",
  title: "Instagram",
  value: "https://instagram.com/",
  url: "https://instagram.com/",
});
const unknownHit = finding({
  kind: "note",
  title: "Zombo",
  value: "Email registered on zombo.com",
  extra: { domain: "zombo.com" },
});
const holeheGithub = finding({
  kind: "note",
  title: "GitHub",
  value: "Email registered on github.com",
  extra: { domain: "github.com" },
});

assert.equal(isConfirmedSocialFinding(sherlock), true);
assert.equal(isConfirmedSocialFinding(holehe), true);
assert.equal(isConfirmedSocialFinding(socialscan), true);
assert.equal(isConfirmedSocialFinding(ignorant), true);
assert.equal(isConfirmedSocialFinding(emptyCnam), false);
assert.equal(isConfirmedSocialFinding(ignorantMiss), false);
assert.equal(isConfirmedSocialFinding(notInstalled), false);
assert.equal(isConfirmedSocialFinding(mx), false);
assert.equal(isConfirmedSocialFinding(homepageProfile), false);

const badges = collectConfirmedSocials([
  sherlock,
  maigret,
  holehe,
  socialscan,
  ignorant,
  emptyCnam,
  ignorantMiss,
  notInstalled,
  mx,
  homepageProfile,
  unknownHit,
  holeheGithub,
]);
assert.deepEqual(
  badges.map((row) => row.slug),
  ["github", "instagram", "snapchat", "spotify", "x", "zombo"],
);
assert.equal(badges.find((row) => row.slug === "github")?.url, "https://github.com/stpayne55");
assert.equal(badges.find((row) => row.slug === "instagram")?.url, null);
assert.equal(badges.find((row) => row.slug === "x")?.site, "X");
assert.deepEqual(
  badges.map((row) => row.site),
  ["GitHub", "Instagram", "Snapchat", "Spotify", "X", "Zombo"],
);
assert.ok(badges.every((row) => row.site.trim().length > 0));
assert.equal(resolveSocialSite(unknownHit)?.slug, "zombo");
assert.equal(collectConfirmedSocials([]).length, 0);

console.log("socials_test ok");
