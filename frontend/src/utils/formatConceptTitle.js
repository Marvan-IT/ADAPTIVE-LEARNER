/**
 * Convert concept ID slug to human-readable title.
 * "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS" → "Introduction to Whole Numbers"
 */
export function formatConceptTitle(conceptId) {
  if (!conceptId) return "";
  const parts = conceptId.split(".");
  const slug = parts[parts.length - 1] || conceptId;
  return slug
    .split("_")
    .map((word) => {
      const lower = word.toLowerCase();
      // Keep small words lowercase (unless first word)
      if (["to", "of", "and", "the", "a", "an", "in", "on", "for", "with"].includes(lower)) {
        return lower;
      }
      return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
    })
    .join(" ")
    .replace(/^\w/, (c) => c.toUpperCase()); // Capitalize first word always
}
