// `\p{L}` = Unicode letter; `\p{M}` = combining mark (needed for Tamil virama,
// Devanagari, Thai vowel signs, etc.). Hyphen/space allowed only between words.
export const VALID_INTEREST_RE = /^[\p{L}\p{M}]+(?:[\s-][\p{L}\p{M}]+)*$/u;
export const INTEREST_MIN = 2;
export const INTEREST_MAX = 30;
export const CUSTOM_MAX = 20;

export function preValidate(raw, { existingCustom, predefined }) {
  const v = raw.trim();
  if (v.length < INTEREST_MIN) return { ok: false, code: "too_short", value: v };
  if (v.length > INTEREST_MAX) return { ok: false, code: "too_long", value: v };
  if (!VALID_INTEREST_RE.test(v)) return { ok: false, code: "invalid_chars", value: v };
  const lc = v.toLowerCase();
  if (predefined.some((o) => o.id.toLowerCase() === lc)) return { ok: false, code: "duplicate_predefined", value: v };
  if (existingCustom.some((e) => e.toLowerCase() === lc)) return { ok: false, code: "duplicate_custom", value: v };
  if (existingCustom.length >= CUSTOM_MAX) return { ok: false, code: "limit_reached", value: v };
  return { ok: true, value: v };
}

export const REASON_KEYS = {
  too_short: "settings.interestTooShort",
  too_long: "settings.interestTooLong",
  invalid_chars: "settings.interestInvalid",
  duplicate_predefined: "settings.interestAlreadyPredefined",
  duplicate_custom: "settings.interestDuplicate",
  limit_reached: "settings.interestLimit",
  unrecognized: "settings.interestUnrecognized",
  validator_unavailable: "settings.interestValidatorUnavailable",
};

export function reasonText(t, code) {
  return t(REASON_KEYS[code] || "settings.saveFailed", "Invalid");
}
