import api from "./client";

export const getSubjects = () => api.get("/api/admin/subjects");
export const createSubject = (label) => api.post("/api/admin/subjects", { label });

export const getAdminBooks = (subject) =>
  api.get("/api/admin/books", { params: subject ? { subject } : {} });

export const uploadBook = (file, subject, title) => {
  const form = new FormData();
  form.append("file", file);
  form.append("subject", subject);
  form.append("title", title);
  return api.post("/api/admin/books/upload", form, {
    headers: { "Content-Type": undefined },
  });
};

export const getBookStatus = (slug) => api.get(`/api/admin/books/${slug}/status`);
export const getBookSections = (slug) => api.get(`/api/admin/books/${slug}/sections`);
export const getBookChunks = (slug, conceptId) =>
  api.get(`/api/admin/books/${slug}/chunks/${encodeURIComponent(conceptId)}`);
export const getBookGraph = (slug) => api.get(`/api/admin/books/${slug}/graph`);
export const publishBook = (slug) => api.post(`/api/admin/books/${slug}/publish`);
export const dropBook = (slug) => api.post(`/api/admin/books/${slug}/drop`);
export const retriggerBook = (slug) => api.post(`/api/admin/books/${slug}/retrigger`);
