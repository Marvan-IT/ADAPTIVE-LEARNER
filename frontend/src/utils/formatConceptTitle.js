/**
 * Convert concept ID slug to human-readable title.
 * "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS" → "Introduction to Whole Numbers"
 * "prealgebra2e_0qbw93r_(1)_1.1"               → "Section 1.1"
 */
export function formatConceptTitle(conceptId) {
  if (!conceptId) return "";

  // New-style IDs: slug_N.N at the end (e.g. "prealgebra2e_0qbw93r_(1)_1.1")
  const sectionMatch = conceptId.match(/(\d+\.\d+)$/);
  if (sectionMatch) {
    return `Section ${sectionMatch[1]}`;
  }

  // Old-style dot-separated IDs (e.g. "PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS")
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
