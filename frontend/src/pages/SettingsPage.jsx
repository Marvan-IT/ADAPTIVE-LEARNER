import { useState, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { User, Sparkles, Shield, Eye, EyeOff, LogOut, Check, MessageCircle, Plus, Send, ArrowLeft, Loader } from "lucide-react";
import { useStudent } from "../context/StudentContext";
import { useAuth } from "../context/AuthContext";
import { Avatar } from "../components/ui";
import LanguageSelector from "../components/LanguageSelector";
import { updateStudentProfile } from "../api/students";
import { changePassword } from "../api/auth";
import { createTicket, getTickets, getTicketDetail, sendMessage } from "../api/support";

const TUTOR_STYLES = [
  { id: "default", label: "Default", emoji: "📖" },
  { id: "pirate", label: "Pirate", emoji: "🏴‍☠️" },
  { id: "astronaut", label: "Space", emoji: "🚀" },
  { id: "gamer", label: "Gamer", emoji: "🎮" },
];

const INTEREST_OPTIONS = [
  { id: "Sports", emoji: "⚽" },
  { id: "Gaming", emoji: "🎮" },
  { id: "Music", emoji: "🎵" },
  { id: "Movies", emoji: "🎬" },
  { id: "Food", emoji: "🍕" },
  { id: "Animals", emoji: "🐾" },
  { id: "Space", emoji: "🚀" },
  { id: "Technology", emoji: "💻" },
  { id: "Art", emoji: "🎨" },
  { id: "Nature", emoji: "🌿" },
];

/* ── Shared inline style objects ── */
const cardStyle = { borderRadius: 16, padding: 24, border: "1px solid #E2E8F0", background: "#FFFFFF", marginBottom: 20 };
const labelStyle = { fontSize: 13, fontWeight: 600, color: "#475569", marginBottom: 8, display: "block" };
const inputStyle = { width: "100%", padding: "10px 14px", borderRadius: 12, border: "1.5px solid #E2E8F0", background: "#FAFAFA", fontSize: 14, fontFamily: "inherit", outline: "none", boxSizing: "border-box" };
const primaryBtn = { borderRadius: 9999, padding: "10px 20px", fontSize: 14, fontWeight: 600, border: "none", background: "#F97316", color: "#fff", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s" };
const secondaryBtn = { ...primaryBtn, background: "transparent", border: "1.5px solid #E2E8F0", color: "#64748B" };
const dangerBtn = { ...primaryBtn, background: "#FEF2F2", color: "#EF4444", border: "1.5px solid rgba(239,68,68,0.2)" };

function IconCircle({ bg, color, children }) {
  return (
    <div style={{ width: 36, height: 36, borderRadius: "50%", background: bg, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
      {children}
    </div>
  );
}

function PasswordField({ value, onChange, show, onToggle, placeholder, id, showLabel, hideLabel }) {
  return (
    <div style={{ position: "relative" }}>
      <input
        id={id}
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        style={{ ...inputStyle, paddingRight: 44 }}
      />
      <button
        type="button"
        onClick={onToggle}
        aria-label={show ? hideLabel : showLabel}
        style={{ position: "absolute", right: 12, top: "50%", transform: "translateY(-50%)", background: "none", border: "none", cursor: "pointer", padding: 0, color: "#94A3B8", display: "flex", alignItems: "center" }}
      >
        {show ? <EyeOff size={16} /> : <Eye size={16} />}
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const { t } = useTranslation();
  const { student, logout, refreshStudent } = useStudent();
  const { user } = useAuth();

  const [displayName, setDisplayName] = useState("");
  const [age, setAge] = useState("");
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState(null);

  const [tutorStyle, setTutorStyle] = useState("default");
  const [interests, setInterests] = useState([]);
  const [customInterest, setCustomInterest] = useState("");
  const [prefsSaving, setPrefsSaving] = useState(false);
  const [prefsMsg, setPrefsMsg] = useState(null);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [showCurrentPw, setShowCurrentPw] = useState(false);
  const [showNewPw, setShowNewPw] = useState(false);
  const [showConfirmPw, setShowConfirmPw] = useState(false);
  const [pwSaving, setPwSaving] = useState(false);
  const [pwMsg, setPwMsg] = useState(null);

  const [tickets, setTickets] = useState([]);
  const [ticketsLoading, setTicketsLoading] = useState(false);
  const [activeTicket, setActiveTicket] = useState(null);
  const [activeMessages, setActiveMessages] = useState([]);
  const [msgLoading, setMsgLoading] = useState(false);
  const [newTicketOpen, setNewTicketOpen] = useState(false);
  const [ticketSubject, setTicketSubject] = useState("");
  const [ticketMessage, setTicketMessage] = useState("");
  const [ticketCreating, setTicketCreating] = useState(false);
  const [replyText, setReplyText] = useState("");
  const [replySending, setReplySending] = useState(false);

  const loadTickets = useCallback(async () => {
    setTicketsLoading(true);
    try {
      const res = await getTickets(50, 0);
      setTickets(res.data.tickets || res.data || []);
    } catch { setTickets([]); }
    finally { setTicketsLoading(false); }
  }, []);

  useEffect(() => { loadTickets(); }, [loadTickets]);

  const openTicketDetail = async (ticket) => {
    setActiveTicket(ticket);
    setMsgLoading(true);
    try {
      const res = await getTicketDetail(ticket.id);
      setActiveMessages(res.data.messages || []);
    } catch { setActiveMessages([]); }
    finally { setMsgLoading(false); }
  };

  const handleCreateTicket = async () => {
    if (!ticketSubject.trim() || !ticketMessage.trim()) return;
    setTicketCreating(true);
    try {
      await createTicket(ticketSubject.trim(), ticketMessage.trim());
      setTicketSubject(""); setTicketMessage(""); setNewTicketOpen(false);
      await loadTickets();
    } catch { /* ignore */ }
    finally { setTicketCreating(false); }
  };

  const handleSendReply = async () => {
    if (!replyText.trim() || !activeTicket) return;
    setReplySending(true);
    try {
      await sendMessage(activeTicket.id, replyText.trim());
      setReplyText("");
      const res = await getTicketDetail(activeTicket.id);
      setActiveMessages(res.data.messages || []);
    } catch { /* ignore */ }
    finally { setReplySending(false); }
  };

  useEffect(() => {
    if (student) {
      setDisplayName(student.display_name || "");
      setAge(student.age != null ? String(student.age) : "");
      setTutorStyle(student.preferred_style || "default");
      setInterests(student.interests || []);
    }
  }, [student]);

  const handleSaveProfile = async () => {
    setProfileSaving(true); setProfileMsg(null);
    try {
      const data = { display_name: displayName.trim() };
      data.age = age ? parseInt(age, 10) : null;
      await updateStudentProfile(student.id, data);
      await refreshStudent();
      setProfileMsg({ type: "success", text: t("settings.saved", "Saved successfully") });
    } catch (err) {
      setProfileMsg({ type: "error", text: err.response?.data?.detail || t("settings.saveFailed", "Failed to save") });
    } finally { setProfileSaving(false); setTimeout(() => setProfileMsg(null), 3000); }
  };

  const handleSavePrefs = async () => {
    setPrefsSaving(true); setPrefsMsg(null);
    try {
      await updateStudentProfile(student.id, { preferred_style: tutorStyle, interests });
      await refreshStudent();
      setPrefsMsg({ type: "success", text: t("settings.saved", "Saved successfully") });
    } catch (err) {
      setPrefsMsg({ type: "error", text: err.response?.data?.detail || t("settings.saveFailed", "Failed to save") });
    } finally { setPrefsSaving(false); setTimeout(() => setPrefsMsg(null), 3000); }
  };

  const handleChangePassword = async () => {
    if (newPw !== confirmPw) { setPwMsg({ type: "error", text: t("settings.passwordMismatch", "Passwords do not match") }); return; }
    setPwSaving(true); setPwMsg(null);
    try {
      await changePassword(currentPw, newPw);
      setPwMsg({ type: "success", text: t("settings.passwordChanged", "Password changed successfully") });
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
    } catch (err) {
      setPwMsg({ type: "error", text: err.response?.data?.detail || t("settings.passwordFailed", "Failed to change password") });
    } finally { setPwSaving(false); setTimeout(() => setPwMsg(null), 5000); }
  };

  const toggleInterest = (id) => setInterests((prev) => prev.includes(id) ? prev.filter((i) => i !== id) : [...new Set([...prev, id])]);
  const addCustomInterest = () => { const v = customInterest.trim(); if (v && !interests.includes(v)) setInterests((p) => [...p, v]); setCustomInterest(""); };

  const StatusBadge = ({ status }) => (
    <span style={{ fontSize: 11, fontWeight: 700, padding: "3px 10px", borderRadius: 9999, background: status === "open" ? "#DCFCE7" : "#F1F5F9", color: status === "open" ? "#16A34A" : "#94A3B8" }}>
      {status === "open" ? t("support.open", "Open") : t("support.closed", "Closed")}
    </span>
  );

  const InlineMsg = ({ msg }) => msg ? (
    <span style={{ fontSize: 13, fontWeight: 500, color: msg.type === "success" ? "#22C55E" : "#EF4444", display: "inline-flex", alignItems: "center", gap: 4 }}>
      {msg.type === "success" && <Check size={14} />} {msg.text}
    </span>
  ) : null;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
    <div style={{ maxWidth: 760, margin: "0 auto" }}>
      <h1 style={{ fontSize: 28, fontWeight: 700, fontFamily: "'Outfit', sans-serif", color: "#0F172A", marginBottom: 28 }}>
        {t("nav.settings")}
      </h1>

      {/* ══════ 1. Profile ══════ */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <IconCircle bg="#FFF7ED"><User size={18} color="#F97316" /></IconCircle>
          <h2 style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Outfit', sans-serif", color: "#0F172A", margin: 0 }}>{t("settings.profile", "Profile")}</h2>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 20 }}>
          <Avatar name={student?.display_name || "User"} size="lg" />
          <div>
            <div style={{ fontSize: 16, fontWeight: 600, color: "#0F172A" }}>{student?.display_name}</div>
            <div style={{ fontSize: 13, color: "#94A3B8", marginTop: 2 }}>{user?.email}</div>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div>
            <label style={labelStyle} htmlFor="s-name">{t("settings.displayName", "Display Name")}</label>
            <input id="s-name" value={displayName} onChange={(e) => setDisplayName(e.target.value)} style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle} htmlFor="s-email">{t("settings.email", "Email")}</label>
            <input id="s-email" value={user?.email || ""} disabled style={{ ...inputStyle, opacity: 0.6, cursor: "not-allowed" }} />
          </div>
          <div>
            <label style={labelStyle} htmlFor="s-age">{t("settings.age", "Age")}</label>
            <input id="s-age" type="number" value={age} onChange={(e) => setAge(e.target.value)} min={5} max={120} placeholder="—" style={inputStyle} />
          </div>
          <div>
            <label style={labelStyle}>{t("settings.language", "Language")}</label>
            <LanguageSelector compact={false} />
          </div>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 20 }}>
          <button onClick={handleSaveProfile} disabled={profileSaving || !displayName.trim()} style={{ ...primaryBtn, opacity: profileSaving || !displayName.trim() ? 0.5 : 1 }}>
            {profileSaving ? t("settings.saving", "Saving...") : t("settings.saveProfile", "Save Profile")}
          </button>
          <InlineMsg msg={profileMsg} />
        </div>
      </div>

      {/* ══════ 2. Interests & Tutor Style ══════ */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <IconCircle bg="#FAF5FF"><Sparkles size={18} color="#8B5CF6" /></IconCircle>
          <h2 style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Outfit', sans-serif", color: "#0F172A", margin: 0 }}>{t("settings.tutorStyle", "Interests & Tutor Style")}</h2>
        </div>

        {/* Tutor Style */}
        <div style={{ marginBottom: 20 }}>
          <label style={labelStyle}>{t("customize.style", "Tutor Style")}</label>
          <p style={{ fontSize: 12, color: "#94A3B8", margin: "0 0 12px" }}>{t("settings.tutorStyleHint", "Choose how your AI tutor talks to you during lessons")}</p>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
            {TUTOR_STYLES.map(({ id, label, emoji }) => (
              <button key={id} onClick={() => setTutorStyle(id)} style={{
                padding: "8px 16px", borderRadius: 9999, fontSize: 13, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
                border: tutorStyle === id ? "2px solid #F97316" : "1.5px solid #E2E8F0",
                background: tutorStyle === id ? "#FFF7ED" : "transparent",
                color: tutorStyle === id ? "#F97316" : "#64748B",
              }}>
                {emoji} {t(`style.${id}`, label)}
              </button>
            ))}
          </div>
        </div>

        {/* Interests */}
        <div>
          <label style={labelStyle}>
            {t("customize.interests", "Interests")} <span style={{ fontWeight: 400, color: "#94A3B8" }}>({t("customize.interestsHint", "optional — makes examples fun")})</span>
          </label>
          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
            {INTEREST_OPTIONS.map(({ id, emoji }) => {
              const sel = interests.includes(id);
              return (
                <button key={id} onClick={() => toggleInterest(id)} style={{
                  padding: "6px 14px", borderRadius: 9999, fontSize: 12, fontWeight: 600, cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
                  border: sel ? "2px solid #F97316" : "1.5px solid #E2E8F0",
                  background: sel ? "#FFF7ED" : "transparent",
                  color: sel ? "#F97316" : "#64748B",
                }}>
                  {emoji} {id}
                </button>
              );
            })}
          </div>
          {/* Custom interests */}
          {interests.filter((i) => !INTEREST_OPTIONS.some((o) => o.id === i)).length > 0 && (
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              {interests.filter((i) => !INTEREST_OPTIONS.some((o) => o.id === i)).map((interest) => (
                <span key={interest} onClick={() => toggleInterest(interest)} style={{
                  padding: "4px 12px", borderRadius: 9999, background: "#FFF7ED", color: "#F97316", fontSize: 12, fontWeight: 600, cursor: "pointer", border: "1px solid rgba(249,115,22,0.3)",
                }}>
                  {interest} ✕
                </span>
              ))}
            </div>
          )}
          <input
            value={customInterest}
            onChange={(e) => setCustomInterest(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustomInterest(); } }}
            placeholder={t("customize.addInterest", "Type topic and press Enter...")}
            style={inputStyle}
          />
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 20 }}>
          <button onClick={handleSavePrefs} disabled={prefsSaving} style={{ ...primaryBtn, opacity: prefsSaving ? 0.5 : 1 }}>
            {prefsSaving ? t("settings.saving", "Saving...") : t("settings.savePreferences", "Save Preferences")}
          </button>
          <InlineMsg msg={prefsMsg} />
        </div>
      </div>

      {/* ══════ 3. Help & Support ══════ */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <IconCircle bg="#FEF3C7"><MessageCircle size={18} color="#D97706" /></IconCircle>
          <h2 style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Outfit', sans-serif", color: "#0F172A", margin: 0 }}>{t("settings.helpSupport", "Help & Support")}</h2>
        </div>

        {activeTicket ? (
          /* ── Active ticket detail ── */
          <div>
            <button onClick={() => { setActiveTicket(null); setActiveMessages([]); }} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 13, fontWeight: 600, color: "#F97316", background: "none", border: "none", cursor: "pointer", fontFamily: "inherit", padding: 0, marginBottom: 16 }}>
              <ArrowLeft size={14} /> {t("support.backToTickets", "Back to tickets")}
            </button>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <h3 style={{ fontSize: 15, fontWeight: 700, color: "#0F172A", margin: 0 }}>{activeTicket.subject}</h3>
              <StatusBadge status={activeTicket.status} />
            </div>

            {/* Messages */}
            <div style={{ border: "1px solid #E2E8F0", borderRadius: 14, padding: 16, marginBottom: 14, maxHeight: 340, overflowY: "auto", display: "flex", flexDirection: "column", gap: 10 }}>
              {msgLoading ? (
                <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
                  <Loader size={20} style={{ color: "#94A3B8", animation: "spin 1s linear infinite" }} />
                </div>
              ) : activeMessages.length === 0 ? (
                <p style={{ fontSize: 13, color: "#94A3B8", textAlign: "center", padding: "20px 0" }}>{t("support.noMessages", "No messages yet")}</p>
              ) : activeMessages.map((msg) => (
                <div key={msg.id} style={{
                  alignSelf: msg.sender_role === "student" ? "flex-end" : "flex-start",
                  maxWidth: "80%", padding: "10px 14px",
                  borderRadius: msg.sender_role === "student" ? "14px 14px 4px 14px" : "14px 14px 14px 4px",
                  background: msg.sender_role === "student" ? "#FFF7ED" : "#F8FAFC",
                  border: msg.sender_role === "student" ? "1px solid rgba(249,115,22,0.15)" : "1px solid #E2E8F0",
                  fontSize: 14, color: "#0F172A",
                }}>
                  <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 4, color: msg.sender_role === "student" ? "#EA580C" : "#64748B" }}>
                    {msg.sender_role === "student" ? t("support.you", "You") : (msg.sender_name || t("support.admin", "Admin"))}
                  </div>
                  <div style={{ lineHeight: 1.6, whiteSpace: "pre-wrap" }}>{msg.content}</div>
                  <div style={{ fontSize: 11, color: "#94A3B8", marginTop: 4, textAlign: "right" }}>
                    {new Date(msg.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                  </div>
                </div>
              ))}
            </div>

            {activeTicket.status === "open" && (
              <div style={{ display: "flex", gap: 10 }}>
                <input value={replyText} onChange={(e) => setReplyText(e.target.value)}
                  onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSendReply(); } }}
                  placeholder={t("support.placeholder", "Type your message...")}
                  style={{ ...inputStyle, flex: 1 }} />
                <button onClick={handleSendReply} disabled={replySending || !replyText.trim()}
                  style={{ ...primaryBtn, padding: "10px 16px", display: "flex", alignItems: "center", gap: 4, opacity: replySending || !replyText.trim() ? 0.5 : 1 }}>
                  <Send size={14} />
                </button>
              </div>
            )}
          </div>
        ) : (
          /* ── Ticket list view ── */
          <div>
            {newTicketOpen ? (
              <div style={{ border: "1px solid #E2E8F0", borderRadius: 14, padding: 20, marginBottom: 16, background: "#FAFAFA" }}>
                <h3 style={{ fontSize: 15, fontWeight: 700, color: "#0F172A", margin: "0 0 16px", fontFamily: "'Outfit', sans-serif" }}>{t("support.newTicket", "New Ticket")}</h3>
                <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
                  <input value={ticketSubject} onChange={(e) => setTicketSubject(e.target.value)}
                    placeholder={t("support.subjectPlaceholder", "Brief description of your issue")} style={inputStyle} />
                  <textarea value={ticketMessage} onChange={(e) => setTicketMessage(e.target.value)}
                    placeholder={t("support.message", "Describe your issue in detail...")} rows={4}
                    style={{ ...inputStyle, resize: "none" }} />
                </div>
                <div style={{ display: "flex", gap: 10, marginTop: 16 }}>
                  <button onClick={handleCreateTicket} disabled={ticketCreating || !ticketSubject.trim() || !ticketMessage.trim()}
                    style={{ ...primaryBtn, opacity: ticketCreating || !ticketSubject.trim() || !ticketMessage.trim() ? 0.5 : 1 }}>
                    {ticketCreating ? t("settings.saving", "Saving...") : t("support.send", "Send")}
                  </button>
                  <button onClick={() => { setNewTicketOpen(false); setTicketSubject(""); setTicketMessage(""); }} style={secondaryBtn}>
                    {t("confirm.cancel", "Cancel")}
                  </button>
                </div>
              </div>
            ) : (
              <button onClick={() => setNewTicketOpen(true)} style={{ ...secondaryBtn, marginBottom: 16, display: "inline-flex", alignItems: "center", gap: 6 }}>
                <Plus size={14} /> {t("support.newTicket", "New Ticket")}
              </button>
            )}

            {ticketsLoading ? (
              <div style={{ display: "flex", justifyContent: "center", padding: "40px 0" }}>
                <Loader size={20} style={{ color: "#94A3B8", animation: "spin 1s linear infinite" }} />
              </div>
            ) : tickets.length === 0 ? (
              <div style={{ textAlign: "center", padding: "40px 0", color: "#94A3B8" }}>
                <MessageCircle size={36} style={{ margin: "0 auto 12px", opacity: 0.3 }} />
                <p style={{ fontSize: 14, fontWeight: 500, margin: 0 }}>{t("support.noTickets", "No support tickets yet")}</p>
              </div>
            ) : (
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {tickets.map((ticket) => (
                  <button key={ticket.id} onClick={() => openTicketDetail(ticket)} style={{
                    width: "100%", textAlign: "left", padding: "14px 16px", borderRadius: 12,
                    border: "1px solid #E2E8F0", background: "#FAFAFA", cursor: "pointer", fontFamily: "inherit", transition: "all 0.15s",
                  }}
                    onMouseEnter={(e) => { e.currentTarget.style.borderColor = "#F97316"; e.currentTarget.style.background = "#FFF7ED"; }}
                    onMouseLeave={(e) => { e.currentTarget.style.borderColor = "#E2E8F0"; e.currentTarget.style.background = "#FAFAFA"; }}
                  >
                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: 14, fontWeight: 600, color: "#0F172A", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ticket.subject}</span>
                      <StatusBadge status={ticket.status} />
                    </div>
                    {ticket.last_message_preview && (
                      <p style={{ fontSize: 12, color: "#64748B", margin: "0 0 4px", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{ticket.last_message_preview}</p>
                    )}
                    <div style={{ fontSize: 11, color: "#94A3B8", display: "flex", alignItems: "center", gap: 8 }}>
                      {new Date(ticket.created_at).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" })}
                      {ticket.unread_count > 0 && (
                        <span style={{ minWidth: 20, height: 20, borderRadius: 9999, backgroundColor: "#EF4444", color: "#fff", fontSize: 11, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 5px" }}>
                          {ticket.unread_count}
                        </span>
                      )}
                    </div>
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* ══════ 4. Account ══════ */}
      <div style={cardStyle}>
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 20 }}>
          <IconCircle bg="#FEF2F2"><Shield size={18} color="#EF4444" /></IconCircle>
          <h2 style={{ fontSize: 18, fontWeight: 700, fontFamily: "'Outfit', sans-serif", color: "#0F172A", margin: 0 }}>{t("settings.account", "Account")}</h2>
        </div>

        {/* Change Password */}
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: "#0F172A", margin: "0 0 16px" }}>{t("settings.changePassword", "Change Password")}</h3>
          <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <label style={labelStyle} htmlFor="current-pw">{t("settings.currentPassword", "Current Password")}</label>
              <PasswordField id="current-pw" value={currentPw} onChange={setCurrentPw} show={showCurrentPw} onToggle={() => setShowCurrentPw((p) => !p)} placeholder="••••••••" showLabel={t("auth.showPassword", "Show password")} hideLabel={t("auth.hidePassword", "Hide password")} />
            </div>
            <div>
              <label style={labelStyle} htmlFor="new-pw">{t("settings.newPassword", "New Password")}</label>
              <PasswordField id="new-pw" value={newPw} onChange={setNewPw} show={showNewPw} onToggle={() => setShowNewPw((p) => !p)} placeholder="••••••••" showLabel={t("auth.showPassword", "Show password")} hideLabel={t("auth.hidePassword", "Hide password")} />
            </div>
            <div>
              <label style={labelStyle} htmlFor="confirm-pw">{t("settings.confirmPassword", "Confirm New Password")}</label>
              <PasswordField id="confirm-pw" value={confirmPw} onChange={setConfirmPw} show={showConfirmPw} onToggle={() => setShowConfirmPw((p) => !p)} placeholder="••••••••" showLabel={t("auth.showPassword", "Show password")} hideLabel={t("auth.hidePassword", "Hide password")} />
            </div>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, marginTop: 16 }}>
            <button onClick={handleChangePassword} disabled={pwSaving || !currentPw || !newPw || !confirmPw}
              style={{ ...primaryBtn, opacity: pwSaving || !currentPw || !newPw || !confirmPw ? 0.5 : 1 }}>
              {pwSaving ? t("settings.saving", "Saving...") : t("settings.updatePassword", "Update Password")}
            </button>
            <InlineMsg msg={pwMsg} />
          </div>
        </div>

        <hr style={{ border: "none", borderTop: "1px solid #E2E8F0", margin: "20px 0" }} />

        <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
          <button onClick={async () => { await logout(); window.location.href = "/login"; }} style={{ ...secondaryBtn, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, width: "100%" }}>
            <LogOut size={16} /> {t("auth.logout")}
          </button>
          <button disabled style={{ ...dangerBtn, width: "100%", opacity: 0.5, cursor: "not-allowed" }}>
            {t("settings.deleteAccount", "Delete Account")}
          </button>
        </div>
      </div>
    </div>
    </div>
  );
}
