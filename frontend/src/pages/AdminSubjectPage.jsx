import { useState, useEffect, useRef } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getAdminBooks, uploadBook, retriggerBook, dropBook } from "../api/admin";

const STATUS_COLORS = {
  PROCESSING: "#3b82f6",
  READY_FOR_REVIEW: "#f59e0b",
  PUBLISHED: "#10b981",
  DROPPED: "#9ca3af",
  FAILED: "#ef4444",
};

export default function AdminSubjectPage() {
  const { subjectSlug } = useParams();
  const navigate = useNavigate();
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
    if (!uploadFile || !uploadTitle.trim()) return alert("Please enter a title and choose a PDF file.");
    setUploading(true);
    uploadBook(uploadFile, subjectSlug, uploadTitle.trim())
      .then((r) => { navigate(`/admin/books/${r.data.slug}/track`); })
      .catch((e) => { alert(e.response?.data?.detail || "Upload failed"); setUploading(false); });
  };

  const handleRetrigger = (slug) => {
    if (!window.confirm("Retrigger pipeline for this book? This wipes existing data.")) return;
    retriggerBook(slug).then(() => { navigate(`/admin/books/${slug}/track`); }).catch(console.error);
  };

  const handleDelete = (slug, title) => {
    if (!window.confirm(`Permanently delete "${title}"?\n\nThis will erase all chunks, images, graph data and database records. Students will immediately lose access. This cannot be undone.`)) return;
    dropBook(slug)
      .then(() => load())
      .catch((e) => alert(e.response?.data?.detail || "Delete failed"));
  };

  if (loading) return <div style={{ padding: 40 }}>Loading...</div>;

  return (
    <div style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ marginBottom: 24 }}>
        <button onClick={() => navigate("/admin")} style={{ background: "none", border: "none", color: "#3b82f6", cursor: "pointer", fontSize: 14, padding: 0 }}>
          ← Admin Console
        </button>
      </div>

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 24 }}>
        <h2 style={{ margin: 0, textTransform: "capitalize" }}>{subjectSlug.replace(/_/g, " ")}</h2>
        <button onClick={() => setShowUpload(true)}
          style={{ padding: "8px 16px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
          + Upload PDF
        </button>
      </div>

      {showUpload && (
        <div style={{ position: "fixed", inset: 0, background: "rgba(0,0,0,0.4)", display: "flex", alignItems: "center", justifyContent: "center", zIndex: 50 }}>
          <div style={{ background: "#fff", borderRadius: 12, padding: 32, width: 440 }}>
            <h3 style={{ margin: "0 0 20px" }}>Upload Book to {subjectSlug.replace(/_/g, " ")}</h3>
            <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 500 }}>Display Name (shown to students)</label>
            <input value={uploadTitle} onChange={(e) => setUploadTitle(e.target.value)}
              placeholder="e.g. Financial Accounting"
              style={{ width: "100%", padding: "8px 12px", border: "1px solid #d1d5db", borderRadius: 6, marginBottom: 16, boxSizing: "border-box" }} />
            <label style={{ display: "block", marginBottom: 8, fontSize: 14, fontWeight: 500 }}>PDF File</label>
            <input type="file" accept=".pdf" onChange={(e) => setUploadFile(e.target.files[0])}
              style={{ marginBottom: 24 }} />
            <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
              <button onClick={() => { setShowUpload(false); setUploadTitle(""); setUploadFile(null); }}
                style={{ padding: "8px 16px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
                Cancel
              </button>
              <button onClick={handleUpload} disabled={uploading}
                style={{ padding: "8px 16px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", opacity: uploading ? 0.6 : 1 }}>
                {uploading ? "Uploading..." : "Upload & Process"}
              </button>
            </div>
          </div>
        </div>
      )}

      {books.length === 0 ? (
        <div style={{ textAlign: "center", padding: "60px 0", color: "#9ca3af" }}>
          <p style={{ fontSize: 16 }}>No books uploaded yet.</p>
          <p style={{ fontSize: 14 }}>Click + Upload PDF to get started.</p>
        </div>
      ) : (
        <div style={{ border: "1px solid #e5e7eb", borderRadius: 12, overflow: "hidden" }}>
          {books.map((b, i) => (
            <div key={b.slug} style={{ display: "flex", alignItems: "center", padding: "16px 20px", borderBottom: i < books.length - 1 ? "1px solid #f3f4f6" : "none", gap: 12 }}>
              <div style={{ flex: 1 }}>
                <div style={{ fontWeight: 500 }}>{b.title}</div>
                <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 2 }}>
                  {b.created_at ? new Date(b.created_at).toLocaleDateString() : ""}
                </div>
              </div>
              <span style={{ padding: "4px 10px", borderRadius: 12, fontSize: 12, fontWeight: 600, background: STATUS_COLORS[b.status] + "20", color: STATUS_COLORS[b.status] }}>
                {b.status === "PROCESSING" ? "Processing" : b.status === "READY_FOR_REVIEW" ? "Ready" : b.status === "PUBLISHED" ? "Published" : b.status === "DROPPED" ? "Dropped" : "Failed"}
              </span>
              <div style={{ display: "flex", gap: 8 }}>
                {b.status === "PROCESSING" && (
                  <button onClick={() => navigate(`/admin/books/${b.slug}/track`)}
                    style={{ padding: "6px 12px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>Track</button>
                )}
                {b.status === "READY_FOR_REVIEW" && (
                  <button onClick={() => navigate(`/admin/books/${b.slug}/review`)}
                    style={{ padding: "6px 12px", background: "#f59e0b", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>Review</button>
                )}
                {b.status === "PUBLISHED" && (
                  <>
                    <button onClick={() => navigate(`/admin/books/${b.slug}/review`)}
                      style={{ padding: "6px 12px", background: "#10b981", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>View</button>
                    <button onClick={() => handleDelete(b.slug, b.title)}
                      style={{ padding: "6px 12px", background: "#ef4444", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>Delete</button>
                  </>
                )}
                {(b.status === "DROPPED" || b.status === "FAILED") && (
                  <button onClick={() => handleRetrigger(b.slug)}
                    style={{ padding: "6px 12px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer", fontSize: 13 }}>
                    Retrigger
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
