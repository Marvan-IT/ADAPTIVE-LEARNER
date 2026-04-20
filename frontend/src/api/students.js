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

export const updateStudentProfile = (studentId, data) =>
  api.patch(`/api/v2/students/${studentId}/profile`, data);

export const getReviewDue = (studentId) =>
  api.get(`/api/v2/students/${studentId}/review-due`);

export const getCardHistory = (studentId, limit = 50) =>
  api.get(`/api/v2/students/${studentId}/card-history`, { params: { limit } });

export const updateStudentProgress = (studentId, xpDelta, streak) =>
  api.patch(`/api/v2/students/${studentId}/progress`, {
    xp_delta: xpDelta,
    streak: streak,
  });

export const getSessions = (studentId) =>
  api.get(`/api/v2/students/${studentId}/sessions`);

export const getSessionCardInteractions = (sessionId) =>
  api.get(`/api/v2/sessions/${sessionId}/card-interactions`);

export const getStudentBadges = (studentId) =>
  api.get(`/api/v2/students/${studentId}/badges`);

export const getLeaderboard = (limit = 20) =>
  api.get("/api/v2/leaderboard", { params: { limit } });

export const getFeatureFlags = () =>
  api.get("/api/v2/features");

export const getStudentAnalytics = (studentId) =>
  api.get(`/api/v2/students/${studentId}/analytics`);
