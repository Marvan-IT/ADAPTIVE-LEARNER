import api from "./client";

export const getSubjects = () => api.get("/api/admin/subjects");
export const createSubject = (label) => api.post("/api/admin/subjects", { label });
export const deleteSubject = (slug) => api.delete(`/api/admin/subjects/${slug}`);
export const toggleSubjectVisibility = (slug, isHidden) =>
  api.patch(`/api/admin/subjects/${slug}/visibility`, { is_hidden: isHidden });
export const toggleBookVisibility = (slug, isHidden) =>
  api.patch(`/api/admin/books/${slug}/visibility`, { is_hidden: isHidden });
export const renameBook = (slug, title) =>
  api.patch(`/api/admin/books/${slug}/rename`, { title });

export const getAdminBooks = (subject) =>
  api.get("/api/admin/books", { params: subject ? { subject } : {} });

export const uploadBook = (file, subject, title) => {
  const form = new FormData();
  form.append("file", file);
  form.append("subject", subject);
  form.append("title", title);
  return api.post("/api/admin/books/upload", form, {
    headers: { "Content-Type": undefined },
    timeout: 300000, // 5 minutes for large PDF uploads
  });
};

export const getBookStatus = (slug) => api.get(`/api/admin/books/${slug}/status`);
export const getBookSections = (slug) => api.get(`/api/admin/books/${slug}/sections`);
export const getBookChunks = (slug, conceptId) =>
  api.get(`/api/admin/books/${slug}/chunks/${encodeURIComponent(conceptId)}`);
export const getBookGraph = (slug) => api.get(`/api/admin/books/${slug}/graph`);
export const publishBook = (slug) => api.post(`/api/admin/books/${slug}/publish`);
export const dropBook = (slug) => api.post(`/api/admin/books/${slug}/drop`);
export const deleteBook = (slug) => api.delete(`/api/admin/books/${slug}`);
export const retriggerBook = (slug) => api.post(`/api/admin/books/${slug}/retrigger`);

// ── Dashboard ────────────────────────────────────────────────────
export const getDashboard = () => api.get("/api/admin/dashboard");

// ── Student Management ───────────────────────────────────────────
export const getAdminStudents = (params) =>
  api.get("/api/admin/students", { params });
export const getAdminStudentDetail = (id) =>
  api.get(`/api/admin/students/${id}`);
export const updateAdminStudent = (id, data) =>
  api.patch(`/api/admin/students/${id}`, data);
export const toggleStudentAccess = (id, isActive) =>
  api.patch(`/api/admin/students/${id}/access`, { is_active: isActive });
export const deleteAdminStudent = (id) =>
  api.delete(`/api/admin/students/${id}`);
export const resetStudentPassword = (id) =>
  api.post(`/api/admin/students/${id}/reset-password`);
export const grantStudentMastery = (studentId, conceptId) =>
  api.post(`/api/admin/students/${studentId}/mastery/${encodeURIComponent(conceptId)}`);
export const revokeStudentMastery = (studentId, conceptId) =>
  api.delete(`/api/admin/students/${studentId}/mastery/${encodeURIComponent(conceptId)}`);

// ── Sessions ─────────────────────────────────────────────────────
export const getAdminSessions = (params) =>
  api.get("/api/admin/sessions", { params });

// ── Analytics ────────────────────────────────────────────────────
export const getAdminAnalytics = () => api.get("/api/admin/analytics");

// ── Admin Users ──────────────────────────────────────────────────
export const createAdminUser = (data) =>
  api.post("/api/admin/users/create-admin", data);
export const changeUserRole = (userId, role) =>
  api.patch(`/api/admin/users/${userId}/role`, { role });
export const getAdminUsers = (params) =>
  api.get("/api/admin/users", { params });

// ── Config ───────────────────────────────────────────────────────
export const getAdminConfig = () => api.get("/api/admin/config");
export const updateAdminConfig = (data) =>
  api.patch("/api/admin/config", data);

// ── Chunk Operations ─────────────────────────────────────────────
export const updateChunk = (id, data) =>
  api.patch(`/api/admin/chunks/${id}`, data);
export const toggleChunkVisibility = (id) =>
  api.patch(`/api/admin/chunks/${id}/visibility`);
export const toggleChunkExamGate = (id) =>
  api.patch(`/api/admin/chunks/${id}/exam-gate`);
export const mergeChunks = (chunkId1, chunkId2) =>
  api.post("/api/admin/chunks/merge", { chunk_id_1: chunkId1, chunk_id_2: chunkId2 });
export const splitChunk = (id, position) =>
  api.post(`/api/admin/chunks/${id}/split`, { split_at_position: position });
export const reorderChunks = (conceptId, bookSlug, chunkIds) =>
  api.put(`/api/admin/concepts/${encodeURIComponent(conceptId)}/reorder`, { book_slug: bookSlug, chunk_ids: chunkIds });
export const regenerateChunkEmbedding = (id) =>
  api.post(`/api/admin/chunks/${id}/regenerate-embedding`);
export const regenerateConceptEmbeddings = (conceptId, bookSlug) =>
  api.post(`/api/admin/concepts/${encodeURIComponent(conceptId)}/regenerate-embeddings`, { book_slug: bookSlug });

// ── Section Controls ─────────────────────────────────────────────
export const renameSection = (conceptId, bookSlug, name) =>
  api.patch(`/api/admin/sections/${encodeURIComponent(conceptId)}/rename`, { book_slug: bookSlug, name });
export const toggleSectionOptional = (conceptId, bookSlug, isOptional) =>
  api.patch(`/api/admin/sections/${encodeURIComponent(conceptId)}/optional`, { book_slug: bookSlug, is_optional: isOptional });
export const toggleSectionExamGate = (conceptId, bookSlug, disabled) =>
  api.patch(`/api/admin/sections/${encodeURIComponent(conceptId)}/exam-gate`, { book_slug: bookSlug, disabled });
export const toggleSectionVisibility = (conceptId, bookSlug, isHidden) =>
  api.patch(`/api/admin/sections/${encodeURIComponent(conceptId)}/visibility`, { book_slug: bookSlug, is_hidden: isHidden });
export const promoteToSection = (conceptId, bookSlug, chunkId, label) =>
  api.post(`/api/admin/sections/${encodeURIComponent(conceptId)}/promote`, {
    book_slug: bookSlug,
    chunk_id: chunkId,
    new_section_label: label || undefined,
  });

// ── Graph Overrides ──────────────────────────────────────────────
export const getGraphEdges = (bookSlug) =>
  api.get(`/api/admin/graph/${bookSlug}/edges`);
export const getGraphOverrides = (bookSlug) =>
  api.get(`/api/admin/graph/${bookSlug}/overrides`);
export const modifyGraphEdge = (bookSlug, action, source, target) =>
  api.post(`/api/admin/graph/${bookSlug}/edges`, { action, source, target });
export const deleteGraphOverride = (bookSlug, id) =>
  api.delete(`/api/admin/graph/${bookSlug}/overrides/${id}`);

// ── Progress Reports ──────────────────────────────────────────────
export const getStudentProgressReport = (studentId, period = "week") =>
  api.get(`/api/admin/students/${studentId}/progress-report`, { params: { period } });

// ── Audit / Undo-Redo ─────────────────────────────────────────────
export const getChanges = (params = {}) =>
  api.get("/api/admin/changes", { params });
export const undoChange = (id) => api.post(`/api/admin/changes/${id}/undo`);
export const redoChange = (id) => api.post(`/api/admin/changes/${id}/redo`);
