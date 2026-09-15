import assert from "node:assert/strict";
import type { ModuleStatus, ScannerInfo } from "../src/lib/api.ts";
import { isEnabledScanner, isHiddenModuleStatus, visibleModules } from "../src/lib/modules.ts";

function mod(id: string, status: ModuleStatus["status"]): ModuleStatus {
  return { id, name: id, status, summary: status, duration_ms: 0, finding_count: 0 };
}

assert.equal(isHiddenModuleStatus("skipped"), true);
assert.equal(isHiddenModuleStatus("unavailable"), true);
assert.equal(isHiddenModuleStatus("success"), false);
assert.equal(isHiddenModuleStatus("empty"), false);
assert.equal(isHiddenModuleStatus("queued"), false);
assert.equal(isHiddenModuleStatus("running"), false);
assert.equal(isHiddenModuleStatus("error"), false);
assert.equal(isHiddenModuleStatus("timeout"), false);

const mixed = [
  mod("sherlock", "success"),
  mod("hibp", "skipped"),
  mod("spiderfoot", "unavailable"),
  mod("dorks", "empty"),
  mod("trestle", "skipped"),
  mod("maigret", "running"),
];
assert.deepEqual(
  visibleModules(mixed).map((row) => row.id),
  ["sherlock", "dorks", "maigret"],
);
assert.ok(!visibleModules(mixed).some((row) => row.status === "skipped" || row.status === "unavailable"));
assert.deepEqual(visibleModules([]), []);

const hibp: ScannerInfo = {
  id: "hibp",
  name: "HIBP",
  tool: "hibp",
  description: "",
  accepts: ["email"],
  optional_key: "HIBP_API_KEY",
  limitations: "",
  available: true,
};
const spiderfoot: ScannerInfo = {
  id: "spiderfoot",
  name: "SpiderFoot",
  tool: "sf",
  description: "",
  accepts: ["username", "email", "name", "phone"],
  limitations: "",
  available: false,
};
const phone: ScannerInfo = {
  id: "phone",
  name: "Phone",
  tool: "phonenumbers",
  description: "",
  accepts: ["phone"],
  limitations: "",
  available: true,
};

assert.equal(isEnabledScanner(hibp, { raw: "ada@example.com", type: "email", username_candidates: [] }), true);
assert.equal(isEnabledScanner(spiderfoot, { raw: "ada@example.com", type: "email", username_candidates: [] }), false);
assert.equal(isEnabledScanner(phone, { raw: "ada@example.com", type: "email", username_candidates: [] }), false);
assert.equal(isEnabledScanner(phone, { raw: "+12485206067", type: "phone", username_candidates: [] }), true);

console.log("modules_test ok");
