import api from "./client";

export const getGraphFull = () =>
  api.get("/api/v1/graph/full");

export const getGraphNodes = () =>
  api.get("/api/v1/graph/nodes");

export const getNextConcepts = (masteredConcepts) =>
  api.post("/api/v1/concepts/next", { mastered_concepts: masteredConcepts });

export const getConceptDetail = (conceptId) =>
  api.get(`/api/v1/concepts/${conceptId}`);

export const getConceptImages = (conceptId) =>
  api.get(`/api/v1/concepts/${conceptId}/images`);

export const translateConceptTitles = (titles, language) =>
  api.post("/api/v2/concepts/translate-titles", { titles, language }, { timeout: 180_000 });

export const checkConceptReadiness = (conceptId, studentId) =>
  api.get(`/api/v2/concepts/${encodeURIComponent(conceptId)}/readiness`, {
    params: { student_id: studentId },
  });
