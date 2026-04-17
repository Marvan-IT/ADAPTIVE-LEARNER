import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Upload, Eye, EyeOff } from "lucide-react";
import { getAdminBooks, uploadBook, retriggerBook, dropBook, deleteBook, toggleBookVisibility } from "../api/admin";
import { useToast } from "../components/ui/Toast";
import { useDialog } from "../context/DialogProvider";

function getStatusConfig(t) {
  return {
    PROCESSING:       { label: t("admin.subject.status.processing", "Processing"), bg: "#FFEDD5", color: "#EA580C" },
    READY_FOR_REVIEW: { label: t("admin.subject.status.ready", "Ready"),           bg: "#DBEAFE", color: "#2563EB" },
    PUBLISHED:        { label: t("admin.subject.status.published", "Published"),    bg: "#DCFCE7", color: "#16A34A" },
    DROPPED:          { label: t("admin.subject.status.dropped", "Dropped"),        bg: "#F1F5F9", color: "#64748B" },
    FAILED:           { label: t("admin.subject.status.failed", "Failed"),          bg: "#FEE2E2", color: "#DC2626" },
  };
}

export default function AdminSubjectPage() {
  const { subjectSlug } = useParams();
  const navigate = useNavigate();
  const { t } = useTranslation();
  const { toast } = useToast();
  const dialog = useDialog();
  const STATUS_CONFIG = getStatusConfig(t);
  const [books, setBooks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [uploadTitle, setUploadTitle] = useState("");
  const [uploadFile, setUploadFile] = useState(null);
  const [uploading, setUploading] = useState(false);
  const pollRef = useRef(null);

  const load = () => {
    getAdminBooks(subjectSlug)
      .then((r) => { setBooks(r.data); setLoading(false); })
      .catch(console.error);
  };

  useEffect(() => {
    load();
    pollRef.current = setInterval(() => {
      getAdminBooks(subjectSlug).then((r) => setBooks(r.data)).catch(() => {});
    }, 30000);
    return () => clearInterval(pollRef.current);
  }, [subjectSlug]);

  const handleUpload = () => {
    if (!uploadFile || !uploadTitle.trim()) return toast({ variant: "warning", title: t("admin.subject.validationTitle", "Validation"), description: t("admin.subject.validationMessage", "Please enter a title and choose a PDF file.") });
    setUploading(true);
    uploadBook(uploadFile, subjectSlug, uploadTitle.trim())
      .then((r) => { navigate(`/admin/books/${r.data.slug}/track`); })
      .catch((e) => { toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || e.message || "Upload failed" }); setUploading(false); });
  };

  const handleRetrigger = async (slug) => {
    if (!(await dialog.confirm({ title: t("admin.subject.retriggerTitle", "Retrigger Pipeline"), message: t("admin.subject.retriggerMessage", "Retrigger pipeline for this book? This wipes existing data."), variant: "danger", confirmLabel: t("admin.subject.actionRetrigger", "Retrigger") }))) return;
    retriggerBook(slug).then(() => { navigate(`/admin/books/${slug}/track`); }).catch(console.error);
  };

  const handleToggleBookVisibility = (slug, currentHidden) => {
    toggleBookVisibility(slug, !currentHidden).then(() => load()).catch((e) => toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Failed to toggle visibility" }));
  };

  const handleDrop = async (slug, title) => {
    if (!(await dialog.confirm({ title: t("admin.subject.dropTitle", "Drop Book"), message: t("admin.subject.dropMessage", `Drop "{{title}}"?\n\nThis will reset all extracted content and student learning data but keep the book entry. You can retrigger the pipeline later.`, { title }), variant: "danger", confirmLabel: t("admin.subject.actionDrop", "Drop") }))) return;
    dropBook(slug)
      .then(() => load())
      .catch((e) => toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Drop failed" }));
  };

  const handleDelete = async (slug, title) => {
    if (!(await dialog.confirm({ title: t("admin.subject.deleteTitle", "Delete Book"), message: t("admin.subject.deleteMessage", `Permanently delete "{{title}}"?\n\nThis will erase ALL data: chunks, images, graph, sessions, mastery records, and the book itself. Students will immediately lose access.\n\nThis cannot be undone.`, { title }), variant: "danger", confirmLabel: t("admin.subject.actionDelete", "Delete") }))) return;
    deleteBook(slug)
      .then(() => load())
      .catch((e) => toast({ variant: "danger", title: "Error", description: e.response?.data?.detail || "Delete failed" }));
  };

  if (loading) return <div style={{ padding: "40px 0", textAlign: "center", color: "#94A3B8", fontSize: "14px" }}>{t("common.loading", "Loading...")}</div>;

  return (
    <div style={{ margin: "0 auto" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: "24px" }}>
        <h2 style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", textTransform: "capitalize" }}>
          {subjectSlug.replace(/_/g, " ")}
        </h2>
        <button
          onClick={() => setShowUpload(true)}
          style={{ display: "inline-flex", alignItems: "center", gap: "8px", padding: "10px 20px", backgroundColor: "#EA580C", color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 600, border: "none", cursor: "pointer" }}
        >
          <Upload size={16} />
          {t("admin.subject.uploadPdf", "Upload PDF")}
        </button>
      </div>

      {/* Upload modal */}
      {showUpload && (
        <div style={{ position: "fixed", inset: 0, backgroundColor: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}>
          <div style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "32px", width: "440px", maxWidth: "90vw", boxShadow: "0 8px 32px rgba(0,0,0,0.15)", border: "1px solid #E2E8F0" }}>
            <h3 style={{ fontSize: "18px", fontWeight: 600, color: "#0F172A", marginBottom: "20px" }}>
              Upload Book to {subjectSlug.replace(/_/g, " ")}
            </h3>
            <label style={{ display: "block", marginBottom: "8px", fontSize: "14px", fontWeight: 500, color: "#64748B" }}>
              {t("admin.subject.displayNameLabel", "Display Name (shown to students)")}
            </label>
            <input
              value={uploadTitle}
              onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="e.g. Financial Accounting"
              style={{ width: "100%", padding: "10px 12px", border: "1px solid #E2E8F0", borderRadius: "10px", fontSize: "14px", backgroundColor: "#FFFFFF", color: "#0F172A", marginBottom: "16px", outline: "none", boxSizing: "border-box" }}
            />
            <label style={{ display: "block", marginBottom: "8px", fontSize: "14px", fontWeight: 500, color: "#64748B" }}>
              {t("admin.subject.pdfFileLabel", "PDF File")}
            </label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setUploadFile(e.target.files[0])}
              style={{ marginBottom: "24px", fontSize: "14px", color: "#64748B" }}
            />
            <div style={{ display: "flex", gap: "8px", justifyContent: "flex-end" }}>
              <button
                onClick={() => { setShowUpload(false); setUploadTitle(""); setUploadFile(null); }}
                style={{ padding: "8px 16px", backgroundColor: "#64748B", color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 500, border: "none", cursor: "pointer" }}
              >
                {t("confirm.cancel", "Cancel")}
              </button>
              <button
                onClick={handleUpload}
                disabled={uploading}
                style={{ padding: "8px 16px", backgroundColor: "#EA580C", color: "#FFFFFF", borderRadius: "9999px", fontSize: "14px", fontWeight: 500, border: "none", cursor: "pointer", opacity: uploading ? 0.6 : 1 }}
              >
                {uploading ? t("admin.subject.uploading", "Uploading...") : t("admin.subject.uploadProcess", "Upload & Process")}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Book list */}
      {books.length === 0 ? (
        <div style={{ textAlign: "center", padding: "64px 0", color: "#94A3B8" }}>
          <p style={{ fontSize: "16px" }}>{t("admin.subject.noBooksYet", "No books uploaded yet.")}</p>
          <p style={{ fontSize: "14px", marginTop: "4px" }}>{t("admin.subject.noBooksHint", "Click Upload PDF to get started.")}</p>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "12px" }}>
          {books.map((b) => {
            const statusCfg = STATUS_CONFIG[b.status] || STATUS_CONFIG.FAILED;
            return (
              <div
                key={b.slug}
                style={{ display: "flex", alignItems: "center", gap: "12px", borderRadius: "12px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF", padding: "16px 20px", boxShadow: "0 1px 2px rgba(0,0,0,0.04)", opacity: b.is_hidden ? 0.55 : 1 }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                    <span style={{ fontWeight: 500, color: "#0F172A", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{b.title}</span>
                    {b.is_hidden && (
                      <span style={{ fontSize: "11px", fontWeight: 600, color: "#F59E0B", backgroundColor: "#FEF3C7", padding: "1px 6px", borderRadius: "4px", flexShrink: 0 }}>{t("admin.subject.hidden", "Hidden")}</span>
                    )}
                  </div>
                  <div style={{ fontSize: "12px", color: "#94A3B8", marginTop: "2px" }}>
                    {b.created_at ? new Date(b.created_at).toLocaleDateString() : ""}
                  </div>
                </div>

                {/* Status badge */}
                <span style={{ display: "inline-flex", padding: "4px 12px", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, backgroundColor: statusCfg.bg, color: statusCfg.color }}>
                  {statusCfg.label}
                </span>

                {/* Action buttons */}
                <div style={{ display: "flex", gap: "8px", flexShrink: 0 }}>
                  {b.status === "PROCESSING" && (
                    <button
                      onClick={() => navigate(`/admin/books/${b.slug}/track`)}
                      style={{ padding: "6px 14px", backgroundColor: "#3B82F6", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                    >
                      {t("admin.subject.actionTrack", "Track")}
                    </button>
                  )}
                  {b.status === "READY_FOR_REVIEW" && (
                    <button
                      onClick={() => navigate(`/admin/books/${b.slug}/review`)}
                      style={{ padding: "6px 14px", backgroundColor: "#EA580C", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                    >
                      {t("admin.subject.actionReview", "Review")}
                    </button>
                  )}
                  {b.status === "PUBLISHED" && (
                    <>
                      <button
                        onClick={() => handleToggleBookVisibility(b.slug, b.is_hidden)}
                        title={b.is_hidden ? t("admin.subject.tooltipShow", "Show to students") : t("admin.subject.tooltipHide", "Hide from students")}
                        style={{ padding: "6px 10px", backgroundColor: b.is_hidden ? "#DCFCE7" : "#FEF3C7", color: b.is_hidden ? "#16A34A" : "#F59E0B", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: "4px" }}
                      >
                        {b.is_hidden ? <Eye size={13} /> : <EyeOff size={13} />}
                        {b.is_hidden ? t("admin.subject.actionShow", "Show") : t("admin.subject.actionHide", "Hide")}
                      </button>
                      <button
                        onClick={() => navigate(`/admin/books/${b.slug}/content`)}
                        style={{ padding: "6px 14px", backgroundColor: "#0891B2", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionViewContent", "View Content")}
                      </button>
                      <button
                        onClick={() => handleRetrigger(b.slug)}
                        style={{ padding: "6px 14px", backgroundColor: "#64748B", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionRetrigger", "Retrigger")}
                      </button>
                      <button
                        onClick={() => handleDrop(b.slug, b.title)}
                        style={{ padding: "6px 14px", backgroundColor: "#F59E0B", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionDrop", "Drop")}
                      </button>
                      <button
                        onClick={() => handleDelete(b.slug, b.title)}
                        style={{ padding: "6px 14px", backgroundColor: "#EF4444", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionDelete", "Delete")}
                      </button>
                    </>
                  )}
                  {(b.status === "DROPPED" || b.status === "FAILED" || b.status === "VALIDATION_FAILED" || b.status === "READY_FOR_REVIEW") && (
                    <>
                      <button
                        onClick={() => handleRetrigger(b.slug)}
                        style={{ padding: "6px 14px", backgroundColor: "#64748B", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionRetrigger", "Retrigger")}
                      </button>
                      <button
                        onClick={() => handleDelete(b.slug, b.title)}
                        style={{ padding: "6px 14px", backgroundColor: "#EF4444", color: "#FFF", borderRadius: "9999px", fontSize: "12px", fontWeight: 600, border: "none", cursor: "pointer" }}
                      >
                        {t("admin.subject.actionDelete", "Delete")}
                      </button>
                    </>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
