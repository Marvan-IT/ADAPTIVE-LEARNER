import api from "./client";

const _requireSlug = (slug, fnName) => {
  if (!slug) throw new Error(`${fnName}: bookSlug is required`);
  return slug;
};

export const getGraphFull = (bookSlug) =>
  api.get("/api/v1/graph/full", {
    params: { book_slug: _requireSlug(bookSlug, "getGraphFull") },
  });

export const getNextConcepts = (masteredConcepts, bookSlug) =>
  api.post("/api/v1/concepts/next",
    { mastered_concepts: masteredConcepts },
    { params: { book_slug: _requireSlug(bookSlug, "getNextConcepts") } }
  );

export const getAvailableBooks = () =>
  api.get("/api/v1/books");

export const checkConceptReadiness = (conceptId, studentId, bookSlug) =>
  api.get(`/api/v2/concepts/${encodeURIComponent(conceptId)}/readiness`, {
    params: {
      student_id: studentId,
      book_slug: _requireSlug(bookSlug, "checkConceptReadiness"),
    },
  });

export const getChunksPreview = (bookSlug, conceptId) =>
  api.get(`/api/v2/concepts/${encodeURIComponent(bookSlug)}/${encodeURIComponent(conceptId)}/chunks-preview`);
