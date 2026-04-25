#!/usr/bin/env node
/**
 * Locale parity check — fails with exit code 1 if any non-EN locale
 * has keys missing from or extra to en.json.
 *
 * Usage: node scripts/check-locales.mjs
 * Wired into: npm run lint:locales
 */

import { readFileSync, readdirSync } from "fs";
import { join, dirname } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const LOCALES_DIR = join(__dirname, "../src/locales");

/**
 * Flatten a nested JSON object to dot-notation keys.
 * e.g. { exam: { title: "..." } } -> ["exam.title"]
 */
function flatKeys(obj, prefix) {
  prefix = prefix || "";
  return Object.keys(obj).flatMap((k) => {
    const full = prefix ? prefix + "." + k : k;
    if (typeof obj[k] === "object" && obj[k] !== null) {
      return flatKeys(obj[k], full);
    }
    return [full];
  });
}

const enRaw = readFileSync(join(LOCALES_DIR, "en.json"), "utf8");
const enKeys = new Set(flatKeys(JSON.parse(enRaw)));

let exitCode = 0;

for (const fname of readdirSync(LOCALES_DIR).sort()) {
  if (!fname.endsWith(".json") || fname === "en.json") continue;
  const lang = fname.replace(".json", "");
  const raw = readFileSync(join(LOCALES_DIR, fname), "utf8");
  const keys = new Set(flatKeys(JSON.parse(raw)));

  const missing = [...enKeys].filter((k) => !keys.has(k));
  const extra = [...keys].filter((k) => !enKeys.has(k));

  if (missing.length > 0) {
    console.error(`[${lang}] MISSING ${missing.length} key(s):`);
    missing.forEach((k) => console.error(`  - ${k}`));
    exitCode = 1;
  }
  if (extra.length > 0) {
    console.warn(`[${lang}] EXTRA ${extra.length} key(s) (non-fatal):`);
    extra.forEach((k) => console.warn(`  + ${k}`));
  }
}

if (exitCode === 0) {
  console.log("All locale files are in sync with en.json.");
}

// ── Phase-7 i18n regression: verify two new keys shipped in the bug fix ──────
// Bug fix: dashboard.cardsDone and learning.questionPrefix must be present and
// non-empty in every locale (regression guard — these were absent before phase 7).
const REQUIRED_KEYS = [
  {
    key: "dashboard.cardsDone",
    validate: (v) => typeof v === "string" && v.trim().length > 0,
    hint: "must be a non-empty string",
  },
  {
    key: "learning.questionPrefix",
    validate: (v) =>
      typeof v === "string" && v.trim().length > 0 && v.includes("{{num}}"),
    hint: "must be a non-empty string containing '{{num}}' interpolation",
  },
];

function getNestedValue(obj, dotPath) {
  // Locale files may use dot-notation as flat keys (e.g. "dashboard.cardsDone")
  // OR as nested objects ({ dashboard: { cardsDone: "..." } }).
  // Try flat key first, then nested traversal.
  if (Object.prototype.hasOwnProperty.call(obj, dotPath)) {
    return obj[dotPath];
  }
  return dotPath.split(".").reduce((o, k) => (o && typeof o === "object" ? o[k] : undefined), obj);
}

const ALL_LOCALES = readdirSync(LOCALES_DIR)
  .filter((f) => f.endsWith(".json"))
  .map((f) => ({ lang: f.replace(".json", ""), data: JSON.parse(readFileSync(join(LOCALES_DIR, f), "utf8")) }));

for (const { key, validate, hint } of REQUIRED_KEYS) {
  for (const { lang, data } of ALL_LOCALES) {
    const value = getNestedValue(data, key);
    if (value === undefined) {
      console.error(`[${lang}] MISSING required phase-7 key: "${key}"`);
      exitCode = 1;
    } else if (!validate(value)) {
      console.error(`[${lang}] INVALID phase-7 key "${key}" = ${JSON.stringify(value)} (${hint})`);
      exitCode = 1;
    }
  }
}

if (exitCode === 0) {
  console.log("Phase-7 i18n regression keys validated across all 13 locales.");
}
process.exit(exitCode);
