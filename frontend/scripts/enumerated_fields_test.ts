import assert from "node:assert/strict";
import type { Finding } from "../src/lib/api.ts";
import {
  enumeratedGroupLabel,
  groupEnumeratedFindings,
  isEnumeratedFieldTitle,
} from "../src/lib/enumeratedFields.ts";

function finding(partial: Partial<Finding> & Pick<Finding, "title" | "value">): Finding {
  return {
    kind: "username",
    ...partial,
  };
}

assert.equal(enumeratedGroupLabel("Candidate"), "Candidates");
assert.equal(enumeratedGroupLabel("Candidates"), "Candidates");
assert.equal(enumeratedGroupLabel("Alternate name"), "Aliases");
assert.equal(enumeratedGroupLabel("Alternate names"), "Aliases");
assert.equal(enumeratedGroupLabel("alias"), "Aliases");
assert.equal(enumeratedGroupLabel("Aliases"), "Aliases");
assert.equal(enumeratedGroupLabel("Formatted"), null);
assert.equal(isEnumeratedFieldTitle("Candidate"), true);
assert.equal(isEnumeratedFieldTitle("Primary"), false);

const usernames = groupEnumeratedFindings([
  finding({ title: "Candidate", value: "lisamfraleigh" }),
  finding({ title: "Candidate", value: "lisa.m.fraleigh" }),
]);
assert.equal(usernames.length, 1);
assert.equal(usernames[0].type, "enumerated");
if (usernames[0].type === "enumerated") {
  assert.equal(usernames[0].label, "Candidates");
  assert.deepEqual(
    usernames[0].findings.map((row) => row.value),
    ["lisamfraleigh", "lisa.m.fraleigh"],
  );
}

const mixed = groupEnumeratedFindings([
  finding({ kind: "phone", title: "Formatted", value: "+1 248-520-6067" }),
  finding({ kind: "note", title: "Alternate name", value: "Steve Thomas Payne" }),
  finding({ kind: "note", title: "Alternate name", value: "Steve Payne" }),
  finding({ kind: "metadata", title: "Region", value: "Michigan" }),
]);
assert.equal(mixed.length, 3);
assert.equal(mixed[0].type, "single");
assert.equal(mixed[1].type, "enumerated");
assert.equal(mixed[2].type, "single");
if (mixed[1].type === "enumerated") {
  assert.equal(mixed[1].label, "Aliases");
  assert.deepEqual(
    mixed[1].findings.map((row) => row.value),
    ["Steve Thomas Payne", "Steve Payne"],
  );
}

assert.deepEqual(groupEnumeratedFindings([]), []);

console.log("enumerated_fields_test ok");
