import assert from "node:assert/strict";
import type { Finding, Query } from "../src/lib/api.ts";
import {
  EMPTY_CNAM_DISPLAY,
  curatePhoneCardFindings,
  formatPhoneNumber,
  friendlyCnamValue,
  hasResolvedPhone,
  isPhoneCardClutter,
  pickBestCarrier,
  pickBestLineType,
  pickHeroName,
} from "../src/lib/phoneDisplay.ts";

function finding(partial: Partial<Finding> & Pick<Finding, "title" | "value">): Finding {
  return {
    kind: "metadata",
    ...partial,
  };
}

assert.equal(formatPhoneNumber({ e164: "+12485206067" }), "+1 248-520-6067");
assert.equal(
  formatPhoneNumber({ e164: "+12485206067", national: "2485206067", countryCode: "1" }),
  "+1 248-520-6067",
);
assert.equal(formatPhoneNumber({ raw: "2485206067" }), "+1 248-520-6067");
assert.equal(formatPhoneNumber({ raw: "+1 248 520 6067" }), "+1 248-520-6067");
assert.ok(formatPhoneNumber({ e164: "+447911123456" }).startsWith("+44"));

assert.equal(
  friendlyCnamValue("No caller name on file (common for mobile numbers — CNAM often blank)."),
  EMPTY_CNAM_DISPLAY,
);
assert.equal(friendlyCnamValue(""), EMPTY_CNAM_DISPLAY);
assert.equal(friendlyCnamValue("MODERN ATMOSPHERE LLC"), "MODERN ATMOSPHERE LLC");

const leftovers: Finding[] = [
  finding({ kind: "phone", title: "E.164", value: "+12485206067" }),
  finding({ kind: "phone", title: "Twilio E.164", value: "+12485206067" }),
  finding({ title: "National format", value: "(248) 520-6067" }),
  finding({ title: "Formatted", value: "+1 248-520-6067" }),
  finding({ title: "Validity", value: "valid libphonenumber match" }),
  finding({ title: "Region", value: "Michigan" }),
  finding({ title: "Country", value: "US" }),
  finding({ title: "Line type", value: "fixed or mobile" }),
  finding({ title: "Time zones", value: "America/New_York" }),
  finding({
    kind: "note",
    title: "instagram",
    value: "Number appears registered on instagram.com (not a profile URL)",
  }),
  finding({
    kind: "note",
    title: "Caller name (CNAM)",
    value: "No caller name on file (common for mobile numbers — CNAM often blank).",
  }),
  finding({ title: "Carrier", value: "AT&T Wireless", extra: { source: "twilio" } }),
  finding({ title: "Line type", value: "Mobile", extra: { source: "trestle" } }),
  finding({ title: "Line type", value: "mobile", extra: { source: "twilio" } }),
  finding({ title: "Carrier (dataset)", value: "AT&T" }),
  finding({ title: "Carrier", value: "Trestle Telco", extra: { source: "trestle" } }),
];

assert.ok(leftovers.some((f) => isPhoneCardClutter(f)));

const curated = curatePhoneCardFindings(leftovers, formatPhoneNumber({ e164: "+12485206067" }));
assert.deepEqual(
  curated.map((row) => row.title),
  ["Formatted", "Caller name (CNAM)", "Region", "Country", "Line type", "Carrier"],
);
assert.equal(curated[0].value, "+1 248-520-6067");
assert.equal(curated.find((row) => row.title === "Caller name (CNAM)")?.value, EMPTY_CNAM_DISPLAY);
assert.equal(curated.find((row) => row.title === "Line type")?.value, "Mobile");
assert.equal(pickBestLineType(leftovers)?.value, "Mobile");
assert.equal(pickBestCarrier(leftovers)?.value, "Trestle Telco");
assert.ok(!curated.some((row) => /trestle/i.test(row.title)));
assert.ok(!curated.some((row) => /instagram|e\.164|national format|time zones|validity/i.test(row.title)));
assert.ok(!curated.some((row) => /instagram|appears registered/i.test(row.value)));

const phoneQuery: Query = {
  raw: "+1 248 520 6067",
  type: "phone",
  phone_e164: "+12485206067",
  phone_national: "2485206067",
  phone_country_code: "1",
  username_candidates: [],
};
assert.equal(
  pickHeroName("MEAGAN REDPATH", "Meagan Lynn Redpath"),
  "Meagan Lynn Redpath",
);
assert.equal(
  pickHeroName("Meagan Lynn Redpath", "MEAGAN REDPATH"),
  "Meagan Lynn Redpath",
);
assert.equal(pickHeroName("MEAGAN REDPATH", ""), "MEAGAN REDPATH");
assert.equal(pickHeroName("", "Stephen Thomas Payne"), "Stephen Thomas Payne");
assert.equal(pickHeroName("No caller name on file (common for mobile numbers — CNAM often blank.)"), "");
assert.notEqual(
  pickHeroName("MEAGAN REDPATH", "Meagan Lynn Redpath"),
  "MEAGAN REDPATH",
);

assert.equal(hasResolvedPhone(phoneQuery), true);
assert.equal(hasResolvedPhone({ raw: "ada", type: "name", username_candidates: [] }), false);
assert.equal(
  hasResolvedPhone({ raw: "ada", type: "name", username_candidates: [] }, { emails: [], phones: ["+12485206067"], usernames: [], profiles: 0, images: 0, notes: [] }),
  true,
);

console.log("phone_display_test ok");
