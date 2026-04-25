import { useState, useEffect, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { MessageCircle, Send, Loader, XCircle, RefreshCw } from "lucide-react";
import { getAdminTickets, getAdminTicketDetail, adminReply, updateTicketStatus, markTicketRead } from "../api/support";

const TAB_FILTERS = ["", "open", "closed"];

export default function AdminSupportPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [tickets, setTickets] = useState([]);
  const [loading, setLoading] = useState(true);
  const [activeFilter, setActiveFilter] = useState("");
  const [selectedTicket, setSelectedTicket] = useState(null);
  const [messages, setMessages] = useState([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [replySending, setReplySending] = useState(false);

  const loadTickets = useCallback(async () => {
    setLoading(true);
    try {
      const res = await getAdminTickets(activeFilter, 100, 0);
      setTickets(res.data.tickets || res.data || []);
    } catch { setTickets([]); }
    finally { setLoading(false); }
  }, [activeFilter]);

  useEffect(() => { loadTickets(); }, [loadTickets]);

  const openTicket = async (ticket) => {
    setSelectedTicket(ticket);
    setMsgLoading(true);
    setReplyText("");
    try {
      const res = await getAdminTicketDetail(ticket.id);
      setMessages(res.data.messages || []);
      setSelectedTicket(res.data);
      try { await markTicketRead(ticket.id); } catch { /* ignore */ }
    } catch (err) { console.error("[AdminSupport] Failed to load ticket detail:", err); setMessages([]); }
    finally { setMsgLoading(false); }
  };

  const handleReply = async () => {
    if (!replyText.trim() || !selectedTicket) return;
    setReplySending(true);
    try {
      await adminReply(selectedTicket.id, replyText.trim());
      setReplyText("");
      const res = await getAdminTicketDetail(selectedTicket.id);
      setMessages(res.data.messages || []);
    } catch (err) { console.error("[AdminSupport] Failed to send reply:", err); }
    finally { setReplySending(false); }
  };

  const handleToggleStatus = async () => {
    if (!selectedTicket) return;
    const newStatus = selectedTicket.status === "open" ? "closed" : "open";
    try {
      await updateTicketStatus(selectedTicket.id, newStatus);
      setSelectedTicket((prev) => ({ ...prev, status: newStatus }));
      await loadTickets();
    } catch { /* ignore */ }
  };

  const filterLabel = (f) => {
    if (f === "open") return t("support.open", "Open");
    if (f === "closed") return t("support.closed", "Closed");
    return t("support.all", "All");
  };

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* Header */}
      <div style={{ padding: "24px 28px 16px", borderBottom: "1px solid #E2E8F0" }}>
        <div style={{ display: "flex", alignItems: "center", gap: "12px", marginBottom: "20px" }}>
          <div style={{ width: 36, height: 36, borderRadius: "50%", background: "#FEF3C7", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
            <MessageCircle size={18} color="#D97706" />
          </div>
          <h1 style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", margin: 0, fontFamily: "'Outfit', sans-serif" }}>
            {t("admin.support.title", "Support Tickets")}
          </h1>
        </div>
        <div style={{ display: "flex", gap: "8px" }}>
          {TAB_FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => { setActiveFilter(f); setSelectedTicket(null); }}
              style={{
                padding: "8px 16px", borderRadius: "9999px", fontSize: "13px", fontWeight: 600,
                border: activeFilter === f ? "2px solid #F97316" : "1.5px solid #E2E8F0",
                background: activeFilter === f ? "#FFF7ED" : "transparent",
                color: activeFilter === f ? "#EA580C" : "#64748B",
                cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
              }}
            >
              {filterLabel(f)}
            </button>
          ))}
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>
        {/* Ticket list */}
        <div style={{ width: selectedTicket ? "360px" : "100%", borderRight: selectedTicket ? "1px solid #E2E8F0" : "none", overflowY: "auto", transition: "width 0.2s", flexShrink: 0 }}>
          {loading ? (
            <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
              <Loader size={24} style={{ color: "#94A3B8", animation: "spin 1s linear infinite" }} />
            </div>
          ) : tickets.length === 0 ? (
            <div style={{ textAlign: "center", padding: "60px 20px", color: "#94A3B8" }}>
              <MessageCircle size={40} style={{ margin: "0 auto 16px", opacity: 0.3 }} />
              <p style={{ fontSize: "15px", fontWeight: 500, margin: 0 }}>{t("support.noTickets", "No support tickets yet")}</p>
            </div>
          ) : tickets.map((ticket) => {
            const isSelected = selectedTicket?.id === ticket.id;
            return (
              <button
                key={ticket.id}
                onClick={() => openTicket(ticket)}
                style={{
                  width: "100%", textAlign: "left", padding: "16px 20px",
                  background: isSelected ? "#FFF7ED" : "transparent",
                  border: "none", borderBottom: "1px solid #F1F5F9",
                  borderLeft: isSelected ? "3px solid #F97316" : "3px solid transparent",
                  cursor: "pointer", fontFamily: "inherit",
                  transition: "all 0.15s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "6px" }}>
                  <span style={{ fontSize: "14px", fontWeight: 600, color: "#0F172A", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {ticket.subject}
                  </span>
                  <span style={{
                    fontSize: "11px", fontWeight: 700, padding: "3px 10px", borderRadius: "9999px", flexShrink: 0, marginLeft: "8px",
                    background: ticket.status === "open" ? "#DCFCE7" : "#F1F5F9",
                    color: ticket.status === "open" ? "#16A34A" : "#94A3B8",
                  }}>
                    {ticket.status === "open" ? t("support.open", "Open") : t("support.closed", "Closed")}
                  </span>
                </div>
                <div style={{ fontSize: "12px", color: "#64748B", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                  <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", flex: 1 }}>
                    <span
                      onClick={(e) => { e.stopPropagation(); if (ticket.student_id) navigate(`/admin/students/${ticket.student_id}`); }}
                      style={{ fontWeight: 600, color: ticket.student_id ? "#F97316" : "#64748B", cursor: ticket.student_id ? "pointer" : "default" }}
                    >{ticket.student_name || "Student"}</span> — {ticket.last_message_preview || "..."}
                  </span>
                  {(ticket.unread_count > 0) && (
                    <span style={{ minWidth: "20px", height: "20px", borderRadius: "9999px", backgroundColor: "#EF4444", color: "#fff", fontSize: "11px", fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 5px", flexShrink: 0, marginLeft: "8px" }}>
                      {ticket.unread_count}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: "11px", color: "#94A3B8", marginTop: "6px" }}>
                  {new Date(ticket.updated_at || ticket.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                </div>
              </button>
            );
          })}
        </div>

        {/* Empty conversation panel */}
        {!selectedTicket && tickets.length > 0 && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: "16px", color: "#94A3B8" }}>
            <MessageCircle size={40} style={{ opacity: 0.3 }} />
            <p style={{ fontSize: "15px", fontWeight: 500, margin: 0 }}>{t("admin.support.selectTicket", "Select a ticket to view the conversation")}</p>
          </div>
        )}

        {/* Active conversation panel */}
        {selectedTicket && (
          <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden" }}>
            {/* Ticket header */}
            <div style={{ padding: "16px 24px", borderBottom: "1px solid #E2E8F0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
              <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                {/* Student avatar */}
                <div style={{ width: 40, height: 40, borderRadius: "50%", background: "linear-gradient(135deg, #fb923c, #ea580c)", display: "flex", alignItems: "center", justifyContent: "center", color: "#fff", fontWeight: 700, fontSize: 16, flexShrink: 0 }}>
                  {(selectedTicket.student_name || "S").charAt(0).toUpperCase()}
                </div>
                <div>
                  <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", margin: 0, fontFamily: "'Outfit', sans-serif" }}>{selectedTicket.subject}</h2>
                  <p style={{ fontSize: "13px", color: "#64748B", margin: "2px 0 0" }}>
                    {t("support.from", "From")}:{" "}
                    <span
                      onClick={(e) => { e.stopPropagation(); if (selectedTicket.student_id) navigate(`/admin/students/${selectedTicket.student_id}`); }}
                      style={{ fontWeight: 600, color: "#F97316", cursor: selectedTicket.student_id ? "pointer" : "default", textDecoration: "none" }}
                      onMouseEnter={(e) => { if (selectedTicket.student_id) e.currentTarget.style.textDecoration = "underline"; }}
                      onMouseLeave={(e) => { e.currentTarget.style.textDecoration = "none"; }}
                    >
                      {selectedTicket.student_name || "Student"}
                    </span> — {selectedTicket.status === "open" ? t("support.open", "Open") : t("support.closed", "Closed")}
                  </p>
                </div>
              </div>
              <button
                onClick={handleToggleStatus}
                style={{
                  display: "flex", alignItems: "center", gap: "6px",
                  padding: "8px 16px", borderRadius: "9999px", fontSize: "13px", fontWeight: 600,
                  border: "1.5px solid #E2E8F0", background: "transparent", cursor: "pointer", fontFamily: "inherit",
                  color: selectedTicket.status === "open" ? "#EF4444" : "#22C55E",
                  transition: "all 0.15s",
                }}
              >
                {selectedTicket.status === "open" ? <><XCircle size={14} /> {t("support.close", "Close")}</> : <><RefreshCw size={14} /> {t("support.reopen", "Reopen")}</>}
              </button>
            </div>

            {/* Messages */}
            <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: "12px" }}>
              {msgLoading ? (
                <div style={{ display: "flex", justifyContent: "center", padding: "60px 0" }}>
                  <Loader size={24} style={{ color: "#94A3B8", animation: "spin 1s linear infinite" }} />
                </div>
              ) : messages.map((msg) => (
                <div
                  key={msg.id}
                  style={{
                    alignSelf: msg.sender_role === "admin" ? "flex-end" : "flex-start",
                    maxWidth: "70%",
                    padding: "12px 16px",
                    borderRadius: msg.sender_role === "admin" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                    background: msg.sender_role === "admin" ? "#EFF6FF" : "#FFF7ED",
                    border: msg.sender_role === "admin" ? "1px solid rgba(59,130,246,0.15)" : "1px solid rgba(249,115,22,0.15)",
                    fontSize: "14px", color: "#0F172A",
                  }}
                >
                  <div style={{ fontSize: "12px", fontWeight: 600, marginBottom: "4px", color: msg.sender_role === "admin" ? "#2563EB" : "#EA580C" }}>
                    {msg.sender_role === "admin" ? (msg.sender_name || t("support.admin", "Admin")) : (msg.sender_name || t("support.student", "Student"))}
                  </div>
                  <div style={{ lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{msg.content}</div>
                  <div style={{ fontSize: "11px", color: "#94A3B8", marginTop: "6px", textAlign: "right" }}>
                    {new Date(msg.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              ))}
            </div>

            {/* Reply input */}
            <div style={{ padding: "14px 24px", borderTop: "1px solid #E2E8F0", display: "flex", gap: "10px" }}>
              <input
                value={replyText}
                onChange={(e) => setReplyText(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleReply(); } }}
                placeholder={t("support.placeholder", "Type your message...")}
                style={{ flex: 1, padding: "10px 14px", borderRadius: "12px", border: "1.5px solid #E2E8F0", background: "#FAFAFA", fontSize: "14px", fontFamily: "inherit", outline: "none" }}
              />
              <button
                onClick={handleReply}
                disabled={replySending || !replyText.trim()}
                style={{
                  padding: "10px 18px", borderRadius: "12px", border: "none",
                  background: replySending || !replyText.trim() ? "#E2E8F0" : "#F97316",
                  color: replySending || !replyText.trim() ? "#94A3B8" : "#fff",
                  cursor: replySending || !replyText.trim() ? "not-allowed" : "pointer",
                  display: "flex", alignItems: "center", gap: "6px",
                  fontSize: "14px", fontWeight: 600, fontFamily: "inherit", transition: "all 0.15s",
                }}
              >
                <Send size={15} />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
