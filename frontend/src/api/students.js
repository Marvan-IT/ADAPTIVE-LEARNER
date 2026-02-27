import api from "./client";

export const createStudent = (displayName, interests, preferredStyle = "default", preferredLanguage = "en") =>
  api.post("/api/v2/students", {
    display_name: displayName,
    interests,
    preferred_style: preferredStyle,
    preferred_language: preferredLanguage,
  });

export const getStudent = (studentId) =>
  api.get(`/api/v2/students/${studentId}`);

export const getStudentMastery = (studentId) =>
  api.get(`/api/v2/students/${studentId}/mastery`);

export const listStudents = () => api.get("/api/v2/students");

export const updateLanguage = (studentId, language) =>
  api.patch(`/api/v2/students/${studentId}/language`, { language });

export const getReviewDue = (studentId) =>
  api.get(`/api/v2/students/${studentId}/review-due`);
