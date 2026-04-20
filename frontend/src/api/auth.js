import api from "./client";

export const registerUser = (data) => api.post("/api/v1/auth/register", data);
export const verifyOtp = (email, otp, purpose = "email_verify") => api.post("/api/v1/auth/verify-otp", { email, otp, purpose });
export const loginUser = (email, password) => api.post("/api/v1/auth/login", { email, password });
export const refreshToken = (refresh_token) => api.post("/api/v1/auth/refresh", { refresh_token });
export const getMe = () => api.get("/api/v1/auth/me");
export const forgotPassword = (email) => api.post("/api/v1/auth/forgot-password", { email });
export const resetPassword = (email, otp, new_password) =>
  api.post("/api/v1/auth/reset-password", { email, otp, new_password });
export const resendOtp = (email, purpose) => api.post("/api/v1/auth/resend-otp", { email, purpose });
export const logoutUser = (refresh_token) => api.post("/api/v1/auth/logout", { refresh_token });
export const changePassword = (current_password, new_password) =>
  api.post("/api/v1/auth/change-password", { current_password, new_password });
