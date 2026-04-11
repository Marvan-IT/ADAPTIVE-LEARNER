import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { getSubjects, createSubject } from "../api/admin";

export default function AdminPage() {
  const [subjects, setSubjects] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [newLabel, setNewLabel] = useState("");
  const navigate = useNavigate();

  const load = () => {
    setLoading(true);
    getSubjects()
      .then((r) => setSubjects(r.data))
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => { load(); }, []);

  const handleAddSubject = () => {
    if (!newLabel.trim()) return;
    createSubject(newLabel.trim())
      .then(() => { setNewLabel(""); setShowForm(false); load(); })
      .catch((e) => alert(e.response?.data?.detail || "Failed to create subject"));
  };

  if (loading) return <div style={{ padding: 40 }}>Loading...</div>;

  return (
    <div style={{ padding: 40, fontFamily: "sans-serif", maxWidth: 900, margin: "0 auto" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
        <h1 style={{ margin: 0, fontSize: 28 }}>ADA Admin Console</h1>
        <button onClick={() => setShowForm(!showForm)}
          style={{ padding: "8px 16px", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
          + Add Subject
        </button>
      </div>

      {showForm && (
        <div style={{ display: "flex", gap: 8, marginBottom: 24 }}>
          <input value={newLabel} onChange={(e) => setNewLabel(e.target.value)}
            placeholder="Subject name (e.g. Physics)"
            style={{ flex: 1, padding: "8px 12px", border: "1px solid #d1d5db", borderRadius: 6, fontSize: 14 }} />
          <button onClick={handleAddSubject}
            style={{ padding: "8px 16px", background: "#10b981", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            Create
          </button>
          <button onClick={() => setShowForm(false)}
            style={{ padding: "8px 16px", background: "#6b7280", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
            Cancel
          </button>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 16 }}>
        {subjects.map((s) => (
          <div key={s.slug} style={{ border: "1px solid #e5e7eb", borderRadius: 12, padding: 24, background: "#fff" }}>
            <h3 style={{ margin: "0 0 8px", fontSize: 18 }}>{s.label}</h3>
            <p style={{ margin: "0 0 16px", color: "#6b7280", fontSize: 14 }}>{s.book_count} book{s.book_count !== 1 ? "s" : ""}</p>
            <button onClick={() => navigate(`/admin/subjects/${s.slug}`)}
              style={{ width: "100%", padding: "8px 0", background: "#3b82f6", color: "#fff", border: "none", borderRadius: 6, cursor: "pointer" }}>
              Open
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
