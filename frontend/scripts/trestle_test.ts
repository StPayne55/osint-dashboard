import assert from "node:assert/strict";
import type { Finding } from "../src/lib/api.ts";
import {
  addressDisplayFields,
  formatTrestleField,
  groupTrestlePhoneFindings,
  isCompetingDisplayName,
  isDirectNameMatch,
  isDirectOwnerMatch,
  isTrestleCurrentAddress,
  normalizePersonName,
  ownerDisplayFields,
  ownersForDisplay,
  partitionOwnersByPrimary,
  takeCompetingCallerName,
} from "../src/lib/trestle.ts";

function finding(partial: Partial<Finding> & Pick<Finding, "title" | "value">): Finding {
  return {
    kind: "note",
    ...partial,
  };
}

const ownerA = finding({
  title: "Name",
  value: "S Fraileigh",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 0,
    owner: {
      age_range: "35-39",
      gender: "Male",
      type: "Person",
      link_to_phone_start_date: "2015-03-01",
    },
  },
});

const current = finding({
  title: "Current address",
  value: "200 New St Apt 4, Detroit, MI 48201",
  extra: {
    source: "trestle",
    finding_type: "trestle_address",
    owner_index: 0,
    owner_name: "S Fraileigh",
    is_current: true,
    fields: {
      location_type: "Address",
      street_line_1: "200 New St",
      street_line_2: "Apt 4",
      city: "Detroit",
      postal_code: "48201",
      zip4: "48201-1234",
      state_code: "MI",
      country_code: "US",
      lat_long: { latitude: 42.3314, longitude: -83.0458, accuracy: "Rooftop" },
      delivery_point: "MultiUnit",
      link_to_person_start_date: "2021-09-15",
      id: "Location.new",
    },
  },
});

const older = finding({
  title: "Address",
  value: "100 Old St, Warren, MI 48088",
  extra: {
    source: "trestle",
    finding_type: "trestle_address",
    owner_index: 0,
    is_current: false,
    fields: {
      street_line_1: "100 Old St",
      city: "Warren",
      state_code: "MI",
      postal_code: "48088",
      link_to_person_start_date: "2012-04-01",
    },
  },
});

const ownerB = finding({
  title: "Name",
  value: "A Fraileigh",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 1,
    owner: { gender: "Female" },
  },
});

const ownerBAddress = finding({
  title: "Current address",
  value: "50 Other Rd, Sterling Heights, MI 48310",
  extra: {
    source: "trestle",
    finding_type: "trestle_address",
    owner_index: 1,
    is_current: true,
    fields: { street_line_1: "50 Other Rd", city: "Sterling Heights", state_code: "MI" },
  },
});

const lineType = finding({
  kind: "metadata",
  title: "Line type",
  value: "Mobile",
  extra: { source: "trestle" },
});

const business = finding({
  title: "Name",
  value: "Payne Stephen",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 2,
    owner_type: "Business",
    owner: { type: "Business", id: "Business.xyz" },
  },
});

const grouped = groupTrestlePhoneFindings([lineType, older, current, ownerA, ownerB, ownerBAddress, business]);
assert.equal(grouped.leftover.length, 1);
assert.equal(grouped.leftover[0].title, "Line type");
assert.equal(grouped.owners.length, 3);
assert.equal(grouped.owners[0].name, "S Fraileigh");
assert.equal(grouped.owners[2].name, "Payne Stephen");
assert.equal(grouped.owners[2].ownerType, "Business");
const visible = ownersForDisplay(grouped.owners);
assert.equal(visible.length, 2);
assert.ok(!visible.some((owner) => owner.name === "Payne Stephen"));
assert.deepEqual(
  ownersForDisplay([grouped.owners[2]]).map((owner) => owner.name),
  ["Payne Stephen"],
);

const personPayne = finding({
  title: "Name",
  value: "Stephen Thomas Payne",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 0,
    owner_type: "Person",
    owner: { type: "Person", id: "Person.abc" },
  },
});
const businessPayne = finding({
  title: "Name",
  value: "Payne Stephen",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 1,
    owner_type: "Business",
    owner: {
      type: "Business",
      id: "Business.69945dde-8672-3d78-8a30-69896d1c92d3",
    },
  },
});
const payneGroup = groupTrestlePhoneFindings([personPayne, businessPayne]);
assert.deepEqual(
  ownersForDisplay(payneGroup.owners).map((owner) => owner.name),
  ["Stephen Thomas Payne"],
);
assert.deepEqual(
  ownerDisplayFields(businessPayne.extra?.owner as Record<string, unknown>).map((row) => row.key),
  ["type"],
);
assert.ok(
  !ownerDisplayFields(businessPayne.extra?.owner as Record<string, unknown>).some((row) =>
    /Business\./.test(row.value),
  ),
);
assert.equal(grouped.owners[0].addresses[0].value, current.value);
assert.equal(isTrestleCurrentAddress(grouped.owners[0].addresses[0]), true);
assert.equal(isTrestleCurrentAddress(grouped.owners[0].addresses[1]), false);
assert.equal(grouped.owners[1].name, "A Fraileigh");

const ownerChips = ownerDisplayFields({
  ...grouped.owners[0].ownerFields,
  id: "Person.abc123",
});
assert.deepEqual(
  ownerChips.map((row) => row.key),
  ["age_range", "gender", "type", "link_to_phone_start_date"],
);
assert.ok(!ownerChips.some((row) => row.key === "firstname" || row.key === "id"));

const currentFields = addressDisplayFields(current.extra?.fields as Record<string, unknown>);
assert.deepEqual(
  currentFields.map((row) => row.key),
  [
    "location_type",
    "street_line_1",
    "street_line_2",
    "city",
    "postal_code",
    "zip4",
    "state_code",
    "country_code",
    "lat_long",
    "delivery_point",
    "link_to_person_start_date",
  ],
);
assert.equal(currentFields.find((row) => row.key === "street_line_1")?.label, "Street address");
assert.equal(currentFields.find((row) => row.key === "street_line_2")?.label, "Address line 2");
assert.equal(currentFields.find((row) => row.key === "postal_code")?.label, "ZIP / Postal code");
assert.equal(currentFields.find((row) => row.key === "zip4")?.label, "ZIP+4");
assert.equal(currentFields.find((row) => row.key === "state_code")?.label, "State");
assert.equal(currentFields.find((row) => row.key === "lat_long")?.label, "Coordinates");
assert.equal(currentFields.find((row) => row.key === "link_to_person_start_date")?.label, "Linked since");
assert.ok(!currentFields.some((row) => row.key === "id"));
assert.equal(formatTrestleField({ latitude: 42.3314, longitude: -83.0458, accuracy: "Rooftop" }), "42.3314, -83.0458 (Rooftop)");

const sparse = addressDisplayFields({ city: "Detroit", invented: "" });
assert.deepEqual(sparse, [{ key: "city", label: "City", value: "Detroit" }]);
assert.deepEqual(
  addressDisplayFields({ zip: "48201", latitude: 42.3, longitude: -83.0 }).map((row) => row.key),
  ["postal_code", "lat_long"],
);
assert.equal(formatTrestleField(null), "");
assert.equal(formatTrestleField(""), "");

assert.equal(normalizePersonName("Stephen J. Payne"), "stephen j payne");
assert.equal(isDirectNameMatch("Stephen Thomas Payne", "STEPHEN THOMAS PAYNE"), true);
assert.equal(isDirectNameMatch("Stephen Thomas Payne", "Stephen J Payne"), false);
assert.equal(isDirectNameMatch("Stephen J. Payne", "Stephen J Payne"), true);
assert.equal(isDirectNameMatch("PAYNE STEPHEN J", "Stephen Thomas Payne"), false);

const stephenThomas = finding({
  title: "Name",
  value: "Stephen Thomas Payne",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 0,
    owner_type: "Person",
    owner: {
      id: "Person.primary",
      type: "Person",
      age_range: "36-40",
      gender: "M",
    },
  },
});
const stephenThomasAlt = finding({
  title: "Alternate name",
  value: "Steve Thomas Payne",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner_field",
    owner_index: 0,
  },
});
const stephenJ = finding({
  title: "Name",
  value: "Stephen J Payne",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 1,
    owner_type: "Person",
    owner: { id: "Person.other", type: "Person", age_range: "36-40", gender: "M" },
  },
});
const hiddenBusiness = finding({
  title: "Name",
  value: "Payne Stephen",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 2,
    owner_type: "Business",
    owner: { type: "Business", id: "Business.hidden" },
  },
});
const paynePeople = groupTrestlePhoneFindings([
  stephenThomas,
  stephenThomasAlt,
  stephenJ,
  hiddenBusiness,
]);
const split = partitionOwnersByPrimary(paynePeople.owners, "Stephen Thomas Payne");
assert.deepEqual(
  split.primary.map((owner) => owner.name),
  ["Stephen Thomas Payne"],
);
assert.deepEqual(split.primary[0].alternateNames, ["Steve Thomas Payne"]);
assert.deepEqual(
  split.competing.map((owner) => owner.name),
  ["Stephen J Payne"],
);
assert.ok(!split.competing.some((owner) => owner.name === "Payne Stephen"));

const sameIdTwin = finding({
  title: "Name",
  value: "Stephen J Payne",
  extra: {
    source: "trestle",
    finding_type: "trestle_owner",
    owner_index: 1,
    owner_type: "Person",
    owner: { id: "Person.primary", type: "Person" },
  },
});
const sameIdGroup = groupTrestlePhoneFindings([stephenThomas, sameIdTwin]);
assert.equal(isDirectOwnerMatch(sameIdGroup.owners[1], "Stephen Thomas Payne", "Person.primary"), true);
assert.deepEqual(
  partitionOwnersByPrimary(sameIdGroup.owners, "Stephen Thomas Payne").competing.map((owner) => owner.name),
  [],
);

const noPrimary = partitionOwnersByPrimary(paynePeople.owners, "");
assert.deepEqual(
  noPrimary.primary.map((owner) => owner.name),
  ["Stephen Thomas Payne", "Stephen J Payne"],
);
assert.deepEqual(noPrimary.competing, []);

const onlyCompeting = partitionOwnersByPrimary(paynePeople.owners, "Meagan Lynn Redpath");
assert.deepEqual(onlyCompeting.primary, []);
assert.deepEqual(
  onlyCompeting.competing.map((owner) => owner.name),
  ["Stephen Thomas Payne", "Stephen J Payne"],
);

assert.equal(isCompetingDisplayName("PAYNE STEPHEN J", "Stephen Thomas Payne"), true);
assert.equal(isCompetingDisplayName("STEPHEN THOMAS PAYNE", "Stephen Thomas Payne"), false);
assert.equal(isCompetingDisplayName("No Caller Name Resolved", "Stephen Thomas Payne"), false);
assert.equal(isCompetingDisplayName("", "Stephen Thomas Payne"), false);
assert.equal(isCompetingDisplayName("PAYNE STEPHEN J", ""), false);

const cnamRow = finding({
  kind: "metadata",
  title: "Caller name (CNAM)",
  value: "PAYNE STEPHEN J",
});
const formattedRow = finding({ kind: "phone", title: "Formatted", value: "+1 248-520-6067" });
const pulled = takeCompetingCallerName([formattedRow, cnamRow], "Stephen Thomas Payne");
assert.equal(pulled.competingCnam?.value, "PAYNE STEPHEN J");
assert.deepEqual(
  pulled.rows.map((row) => row.title),
  ["Formatted"],
);
assert.equal(takeCompetingCallerName([formattedRow, cnamRow], "PAYNE STEPHEN J").competingCnam, null);

console.log("trestle_test ok");
