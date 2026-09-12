import assert from "node:assert/strict";
import { collectPhotoFindings, isImageDork, normalizePhotoUrl, photoDedupeKey } from "../src/lib/photos.ts";
import type { Finding } from "../src/lib/api.ts";

assert.equal(normalizePhotoUrl("javascript:alert(1)"), null);
assert.equal(normalizePhotoUrl("//avatars.githubusercontent.com/u/1"), "https://avatars.githubusercontent.com/u/1");
assert.equal(
  photoDedupeKey("https://www.gravatar.com/avatar/abc?s=256"),
  photoDedupeKey("https://secure.gravatar.com/avatar/abc"),
);

const findings: Finding[] = [
  {
    kind: "image",
    title: "Gravatar avatar",
    value: "https://www.gravatar.com/avatar/abc?s=256&d=404",
    url: "https://www.gravatar.com/avatar/abc?s=256&d=404",
    extra: { source: "gravatar" },
  },
  {
    kind: "profile",
    title: "GitHub",
    value: "https://github.com/torvalds",
    url: "https://github.com/torvalds",
    extra: { ids: { image: "https://avatars.githubusercontent.com/u/1024025" }, source: "maigret" },
  },
];

const photos = collectPhotoFindings(findings);
assert.equal(photos.length, 2);
assert.equal(photos[0].source, "gravatar");
assert.equal(photos[1].source, "maigret");
assert.ok(photos[1].title.includes("GitHub"));

assert.equal(
  isImageDork({
    kind: "link",
    title: "Google Images — quoted name (manual)",
    value: '"Ada Lovelace"',
    url: "https://www.google.com/search?udm=2&tbm=isch&q=%22Ada+Lovelace%22",
    extra: { tab: "images", manual: true },
  }),
  true,
);

console.log("photos helper ok");
