import api from "./client";

// Student endpoints
export const createTicket = (subject, message) =>
  api.post("/api/v2/support/tickets", { subject, message });

export const getTickets = (limit = 20, offset = 0) =>
  api.get("/api/v2/support/tickets", { params: { limit, offset } });

export const getTicketDetail = (ticketId) =>
  api.get(`/api/v2/support/tickets/${ticketId}`);

export const sendMessage = (ticketId, content) =>
  api.post(`/api/v2/support/tickets/${ticketId}/messages`, { content });

export const getUnreadCount = () =>
  api.get("/api/v2/support/unread-count");

// Admin endpoints
export const getAdminTickets = (status = "", limit = 50, offset = 0) =>
  api.get("/api/admin/support/tickets", { params: { status: status || undefined, limit, offset } });

export const getAdminTicketDetail = (ticketId) =>
  api.get(`/api/admin/support/tickets/${ticketId}`);

export const adminReply = (ticketId, content) =>
  api.post(`/api/admin/support/tickets/${ticketId}/messages`, { content });

export const updateTicketStatus = (ticketId, status) =>
  api.patch(`/api/admin/support/tickets/${ticketId}/status`, { status });

export const markTicketRead = (ticketId) =>
  api.patch(`/api/admin/support/tickets/${ticketId}/read`);

export const getAdminUnreadCount = () =>
  api.get("/api/admin/support/unread-count");
