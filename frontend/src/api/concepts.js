import api from "./client";

export const getGraphFull = (bookSlug = "prealgebra") =>
  api.get("/api/v1/graph/full", { params: { book_slug: bookSlug } });

export const getNextConcepts = (masteredConcepts, bookSlug = "prealgebra") =>
  api.post("/api/v1/concepts/next",
    { mastered_concepts: masteredConcepts },
    { params: { book_slug: bookSlug } }
  );

export const getAvailableBooks = () =>
  api.get("/api/v1/books");

export const checkConceptReadiness = (conceptId, studentId, bookSlug = "prealgebra") =>
  api.get(`/api/v2/concepts/${encodeURIComponent(conceptId)}/readiness`, {
    params: { student_id: studentId, book_slug: bookSlug },
  });

export const getChunksPreview = (bookSlug, conceptId) =>
  api.get(`/api/v2/concepts/${encodeURIComponent(bookSlug)}/${encodeURIComponent(conceptId)}/chunks-preview`);
