/**
 * interestValidation.test.js
 *
 * Plain-JS unit tests for the custom-interest validation helpers.
 * No framework, no DOM, no React — runs directly with `node`.
 *
 * Run from the `frontend/` directory:
 *   node src/pages/settings/interestValidation.test.js
 *
 * Business criteria covered:
 *   BC-1  Format rejection codes for empty / too-short / too-long / invalid-chars / digits-only
 *   BC-2  Unicode scripts pass format check (Arabic, Japanese, Tamil, multi-word, hyphenated)
 *   BC-3  Case-insensitive dedupe against existing custom interests
 *   BC-4  Case-insensitive dedupe against predefined interest options
 *   BC-5  Limit enforcement (CUSTOM_MAX = 20)
 *   BC-6  Happy path returns { ok: true, value: trimmedInput }
 *   BC-7  reasonText() maps every code to a defined i18n key
 *   BC-8  REASON_KEYS covers every reason code emitted by preValidate
 */

import { preValidate, reasonText, REASON_KEYS, CUSTOM_MAX } from "./interestValidation.js";

let passed = 0;
let failed = 0;
const failures = [];

function check(name, actual, expected) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (ok) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    failures.push({ name, actual, expected });
    console.log(`  ✗ ${name}`);
    console.log(`      expected: ${JSON.stringify(expected)}`);
    console.log(`      actual:   ${JSON.stringify(actual)}`);
  }
}

function assert(name, cond, detail = "") {
  if (cond) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    failures.push({ name, detail });
    console.log(`  ✗ ${name}${detail ? ` — ${detail}` : ""}`);
  }
}

const ctx = (existing = [], predefined = []) => ({ existingCustom: existing, predefined });

console.log("\nBC-1: Format rejection codes");
check("empty string → too_short",
  preValidate("", ctx()).code, "too_short");
check("single char → too_short",
  preValidate("a", ctx()).code, "too_short");
check("31-char string → too_long",
  preValidate("a".repeat(31), ctx()).code, "too_long");
check("letters + digits → invalid_chars",
  preValidate("abc123", ctx()).code, "invalid_chars");
check("letters + symbol → invalid_chars",
  preValidate("a@b", ctx()).code, "invalid_chars");
check("digits only → invalid_chars",
  preValidate("123", ctx()).code, "invalid_chars");
check("underscore → invalid_chars",
  preValidate("foo_bar", ctx()).code, "invalid_chars");
check("only whitespace → too_short (after trim)",
  preValidate("   ", ctx()).code, "too_short");

console.log("\nBC-2: Unicode format acceptance");
check("Arabic 'محمد' passes",
  preValidate("محمد", ctx()).ok, true);
check("Japanese 'さくら' passes",
  preValidate("さくら", ctx()).ok, true);
check("Tamil 'பழம்' passes",
  preValidate("பழம்", ctx()).ok, true);
check("Multi-word with space 'ice cream' passes",
  preValidate("ice cream", ctx()).ok, true);
check("Hyphenated 'sci-fi' passes",
  preValidate("sci-fi", ctx()).ok, true);
check("Trim leading/trailing spaces",
  preValidate("  fruits  ", ctx()).value, "fruits");

console.log("\nBC-3: Case-insensitive dedupe against existing custom");
check("'Fruits' when existing=['fruits'] → duplicate_custom",
  preValidate("Fruits", ctx(["fruits"])).code, "duplicate_custom");
check("'FRUITS' when existing=['fruits'] → duplicate_custom",
  preValidate("FRUITS", ctx(["fruits"])).code, "duplicate_custom");
check("'fruits' when existing=['Fruits'] → duplicate_custom",
  preValidate("fruits", ctx(["Fruits"])).code, "duplicate_custom");
check("'apples' when existing=['fruits'] → ok",
  preValidate("apples", ctx(["fruits"])).ok, true);

console.log("\nBC-4: Case-insensitive dedupe against predefined");
check("'Sports' when predefined has id 'sports' → duplicate_predefined",
  preValidate("Sports", ctx([], [{ id: "sports" }])).code, "duplicate_predefined");
check("'SPORTS' when predefined has id 'sports' → duplicate_predefined",
  preValidate("SPORTS", ctx([], [{ id: "sports" }])).code, "duplicate_predefined");
check("'Music' when predefined has id 'sports' → ok",
  preValidate("Music", ctx([], [{ id: "sports" }])).ok, true);

console.log("\nBC-5: Limit enforcement");
const twentyItems = Array.from({ length: CUSTOM_MAX }, (_, i) => `item${i + 1}`);
check(`${CUSTOM_MAX}-item existing + new 'fruits' → limit_reached`,
  preValidate("fruits", ctx(twentyItems)).code, "limit_reached");
check(`${CUSTOM_MAX - 1}-item existing + new 'fruits' → ok`,
  preValidate("fruits", ctx(twentyItems.slice(0, CUSTOM_MAX - 1))).ok, true);

console.log("\nBC-6: Happy path");
check("'cooking' returns ok + value",
  preValidate("cooking", ctx()),
  { ok: true, value: "cooking" });
check("'Ice cream' (mixed case) returns ok + value preserving case",
  preValidate("Ice cream", ctx()),
  { ok: true, value: "Ice cream" });

console.log("\nBC-7: reasonText maps codes to i18n keys");
const fakeT = (key) => key; // identity: returns the key itself
check("reasonText for 'too_short'",
  reasonText(fakeT, "too_short"), "settings.interestTooShort");
check("reasonText for 'unrecognized'",
  reasonText(fakeT, "unrecognized"), "settings.interestUnrecognized");
check("reasonText for unknown code → saveFailed fallback",
  reasonText(fakeT, "nonexistent_code"), "settings.saveFailed");

console.log("\nBC-8: REASON_KEYS covers every preValidate output code");
const codesFromPreValidate = new Set([
  preValidate("", ctx()).code,                                              // too_short
  preValidate("a".repeat(31), ctx()).code,                                  // too_long
  preValidate("abc123", ctx()).code,                                        // invalid_chars
  preValidate("Fruits", ctx(["fruits"])).code,                              // duplicate_custom
  preValidate("Sports", ctx([], [{ id: "sports" }])).code,                  // duplicate_predefined
  preValidate("fruits", ctx(twentyItems)).code,                             // limit_reached
]);
for (const code of codesFromPreValidate) {
  assert(`REASON_KEYS has key for '${code}'`, code in REASON_KEYS);
}
// Reason codes also emitted by backend (not preValidate) must be present too:
assert("REASON_KEYS has 'unrecognized' (LLM reject code)",
  "unrecognized" in REASON_KEYS);
assert("REASON_KEYS has 'validator_unavailable' (LLM failure code)",
  "validator_unavailable" in REASON_KEYS);

console.log(`\n${failed === 0 ? "PASS" : "FAIL"}: ${passed} passed, ${failed} failed`);
if (failed > 0) {
  process.exit(1);
}
