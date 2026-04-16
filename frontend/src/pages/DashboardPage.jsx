import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Flame, Star, CheckCircle2, Clock, ChevronRight, Play, BookOpen } from "lucide-react";
import { useStudent } from "../context/StudentContext";
import { useAdaptiveStore } from "../store/adaptiveStore";
import { getSessions, getStudentAnalytics } from "../api/students";
import { getAvailableBooks, getGraphFull } from "../api/concepts";
import { ProgressBar, Card, Button } from "../components/ui";
import LanguageSelector from "../components/LanguageSelector";
import { staggerContainer, staggerItem } from "../theme/themes";
import { formatConceptTitle } from "../utils/formatConceptTitle";


const SUBJECT_COLORS = [
  { bg: "#EFF6FF", text: "#2563EB", bar: "primary" },
  { bg: "#F0FDF4", text: "#16A34A", bar: "success" },
  { bg: "#FAF5FF", text: "#9333EA", bar: "primary" },
  { bg: "#FFF7ED", text: "#EA580C", bar: "primary" },
  { bg: "#FFF1F2", text: "#E11D48", bar: "danger" },
];

const STAT_COLORS = [
  { bg: "#FFF7ED", color: "#F97316" },
  { bg: "#FFFBEB", color: "#F59E0B" },
  { bg: "#F0FDF4", color: "#22C55E" },
  { bg: "#F5F3FF", color: "#8B5CF6" },
];

export default function DashboardPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();

  function getGreeting() {
    const h = new Date().getHours();
    if (h < 12) return t("dashboard.greetingMorning", "Good morning");
    if (h < 17) return t("dashboard.greetingAfternoon", "Good afternoon");
    return t("dashboard.greetingEvening", "Good evening");
  }
  const { student, masteredConcepts } = useStudent();
  const xp = useAdaptiveStore((s) => s.xp);
  const level = useAdaptiveStore((s) => s.level);
  const dailyStreak = useAdaptiveStore((s) => s.dailyStreak);
  const [recentSessions, setRecentSessions] = useState([]);
  const [subjects, setSubjects] = useState([]);
  const [studyTimeSec, setStudyTimeSec] = useState(0);
  const [bookMap, setBookMap] = useState({});

  function displayBookTitle(bookSlug) {
    if (!bookSlug) return "";
    return bookMap[bookSlug]?.title || bookSlug;
  }

  function formatStudyTime(sec) {
    if (sec <= 0) return "0m";
    if (sec < 60) return "< 1m";
    const totalMin = Math.floor(sec / 60);
    const hours = Math.floor(totalMin / 60);
    const mins = totalMin % 60;
    if (hours === 0) return `${mins}m`;
    return `${hours}h ${mins}m`;
  }

  // Fetch recent sessions and study time
  useEffect(() => {
    if (student?.id) {
      getSessions(student.id)
        .then((res) => setRecentSessions((res.data?.sessions || []).slice(0, 5)))
        .catch((err) => console.error("[Dashboard] sessions fetch failed:", err));
      getStudentAnalytics(student.id)
        .then((res) => setStudyTimeSec(res.data?.total_study_time_sec || 0))
        .catch((err) => console.error("[Dashboard] analytics fetch failed:", err));
    }
  }, [student?.id]);

  // Fetch real subjects with progress + last session info
  useEffect(() => {
    if (!student?.id) return;
    const masteredSet = new Set(masteredConcepts || []);

    (async () => {
      try {
        // Fetch books and sessions in parallel
        const [booksRes, sessionsRes] = await Promise.all([
          getAvailableBooks(),
          getSessions(student.id),
        ]);
        const books = booksRes.data || [];
        const allSessions = sessionsRes.data?.sessions || [];
        if (books.length === 0) return;

        // Build a slug→book map and group books by subject
        const slugToBook = {};
        const bySubject = {};
        books.forEach((book) => {
          slugToBook[book.slug] = book;
          const subj = book.subject || "Other";
          if (!bySubject[subj]) bySubject[subj] = [];
          bySubject[subj].push(book);
        });

        setBookMap(slugToBook);

        const subjectData = [];
        for (const [subj, bookList] of Object.entries(bySubject)) {
          let total = 0;
          let mastered = 0;
          const bookSlugs = new Set(bookList.map((b) => b.slug));

          for (const book of bookList) {
            try {
              const graphRes = await getGraphFull(book.slug);
              const nodes = graphRes.data?.nodes || [];
              total += nodes.length;
              mastered += nodes.filter((n) => masteredSet.has(n.concept_id)).length;
            } catch {
              // skip if graph not ready
            }
          }

          // Find the most recent session for this subject
          const lastSession = allSessions.find((s) => bookSlugs.has(s.book_slug));
          const lastBook = lastSession ? slugToBook[lastSession.book_slug] : null;

          if (total > 0) {
            subjectData.push({
              name: subj,
              initial: subj.charAt(0).toUpperCase(),
              mastered,
              total,
              pct: Math.round((mastered / total) * 100),
              lastSession: lastSession || null,
              lastBookTitle: lastBook?.title || null,
            });
          }
        }
        setSubjects(subjectData);
      } catch (err) {
        console.error("[Subjects] Failed to load subjects:", err);
      }
    })();
  }, [student?.id, masteredConcepts]);

  const stats = [
    { icon: Flame, label: t("dashboard.dayStreak", "Day Streak"), value: dailyStreak || 0, color: "bg-orange-50 text-orange-500" },
    { icon: Star, label: t("dashboard.toNextLevel", { xp: 100 - (xp % 100), level: level + 1 }), value: `${xp} XP`, color: "bg-amber-50 text-amber-500" },
    { icon: CheckCircle2, label: t("dashboard.conceptsMastered", "Concepts Mastered"), value: masteredConcepts?.length || 0, color: "bg-emerald-50 text-emerald-500" },
    { icon: Clock, label: t("dashboard.studyTime", "Study Time"), value: formatStudyTime(studyTimeSec), color: "bg-violet-50 text-violet-500" },
  ];

  // Find most recent incomplete session for "Resume" CTA
  const resumeSession = recentSessions.find((s) => s.phase !== "COMPLETED");

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>
      {/* Welcome hero */}
      <div
        style={{
          borderRadius: "16px", padding: "28px", marginBottom: "20px",
          background: "linear-gradient(135deg, #FFF7ED 0%, #FFFFFF 60%)",
          border: "1px solid #E2E8F0",
        }}
      >
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: "16px", marginBottom: "20px" }}>
          <div>
            <h1 style={{ fontSize: "28px", fontWeight: 700, color: "#0F172A", marginBottom: "4px", fontFamily: "'Outfit', sans-serif" }}>
              {getGreeting()}, {student?.display_name || "Learner"}!
            </h1>
            <p style={{ fontSize: "14px", color: "#94A3B8" }}>
              {t("dashboard.resumeHint", "Continue where you left off")}
            </p>
          </div>
          <LanguageSelector prominent />
        </div>

        {resumeSession && (
          <div style={{ display: "flex", alignItems: "center", gap: "16px", padding: "12px 16px", borderRadius: "12px", maxWidth: "520px", backgroundColor: "#FFFFFF", border: "1px solid #E2E8F0", boxShadow: "0 1px 4px rgba(0,0,0,0.04)" }}>
            <div style={{ width: "40px", height: "40px", borderRadius: "50%", backgroundColor: "#F97316", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
              <BookOpen size={18} color="#FFFFFF" />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <p style={{ fontSize: "14px", fontWeight: 600, color: "#0F172A", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {formatConceptTitle(resumeSession.concept_id) || t("dashboard.continueLearning", "Continue Learning")}
              </p>
              <p style={{ fontSize: "12px", color: "#94A3B8" }}>
                {displayBookTitle(resumeSession.book_slug) || t("subjects.mathematics")} &middot; {resumeSession.phase}
              </p>
            </div>
            <button
              onClick={() => navigate(`/learn/${encodeURIComponent(resumeSession.concept_id)}?book_slug=${encodeURIComponent(resumeSession.book_slug || "")}`)}
              style={{ padding: "8px 16px", borderRadius: "9999px", backgroundColor: "#F97316", color: "#FFFFFF", fontSize: "12px", fontWeight: 700, cursor: "pointer", border: "none", flexShrink: 0 }}
            >
              {t("dashboard.resume", "Resume")}
            </button>
          </div>
        )}
      </div>

      {/* Stats row */}
      <motion.div
        variants={staggerContainer}
        initial="hidden"
        animate="show"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: "16px", marginBottom: "28px" }}
      >
        {stats.map((s, idx) => {
          const sc = STAT_COLORS[idx % STAT_COLORS.length];
          return (
            <motion.div
              key={s.label}
              variants={staggerItem}
              style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "20px", border: "1px solid #E2E8F0" }}
            >
              <div style={{ width: "44px", height: "44px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", marginBottom: "12px", backgroundColor: sc.bg, color: sc.color }}>
                <s.icon size={20} />
              </div>
              <p style={{ fontWeight: 700, color: "#0F172A", fontSize: "24px", fontFamily: "'Outfit', sans-serif" }}>
                {s.value}
              </p>
              <p style={{ fontSize: "12px", color: "#94A3B8", marginTop: "2px" }}>{s.label}</p>
            </motion.div>
          );
        })}
      </motion.div>

      {/* My Subjects */}
      <h2 style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", marginBottom: "12px", fontFamily: "'Outfit', sans-serif" }}>
        {t("dashboard.mySubjects", "My Subjects")}
      </h2>
      <motion.div
        key={subjects.length > 0 ? "loaded" : "empty"}
        variants={staggerContainer}
        initial="hidden"
        animate="show"
        style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(300px, 1fr))", gap: "20px", marginBottom: "28px" }}
      >
        {subjects.length > 0
          ? subjects.map((subj, i) => {
              const c = SUBJECT_COLORS[i % SUBJECT_COLORS.length];
              const ls = subj.lastSession;
              return (
                <motion.div
                  key={subj.name}
                  variants={staggerItem}
                  style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "24px", border: "1px solid #E2E8F0", cursor: "pointer", transition: "box-shadow 0.15s" }}
                  onClick={() => {
                    if (ls?.concept_id) {
                      navigate(`/learn/${encodeURIComponent(ls.concept_id)}?book_slug=${encodeURIComponent(ls.book_slug || "")}`);
                    } else {
                      navigate("/map");
                    }
                  }}
                  onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 4px 12px rgba(0,0,0,0.08)"; }}
                  onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; }}
                >
                  <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "14px" }}>
                    <div style={{ width: "48px", height: "48px", borderRadius: "50%", display: "flex", alignItems: "center", justifyContent: "center", fontSize: "16px", fontWeight: 700, backgroundColor: c.bg, color: c.text }}>
                      {subj.initial}
                    </div>
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <p style={{ fontWeight: 600, fontSize: "15px", color: "#0F172A", textTransform: "capitalize" }}>
                        {subj.name}
                      </p>
                      <p style={{ fontSize: "12px", color: "#94A3B8" }}>
                        {subj.mastered}/{subj.total} {t("dashboard.concepts", "concepts")}
                      </p>
                    </div>
                  </div>
                  {ls && (
                    <div style={{ padding: "8px 12px", borderRadius: "8px", backgroundColor: "#F8FAFC", marginBottom: "12px" }}>
                      <p style={{ fontSize: "12px", color: "#64748B", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                        {subj.lastBookTitle && <span style={{ fontWeight: 600 }}>{subj.lastBookTitle}</span>}
                        {subj.lastBookTitle && " · "}
                        {formatConceptTitle(ls.concept_id)}
                      </p>
                      <p style={{ fontSize: "11px", color: "#94A3B8", marginTop: "2px" }}>
                        {ls.phase === "COMPLETED"
                          ? t("dashboard.completed", "Completed")
                          : t("dashboard.continueSection", "Continue where you left off")}
                      </p>
                    </div>
                  )}
                  <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
                    <div style={{ flex: 1 }}>
                      <ProgressBar value={subj.pct} size="sm" color={c.bar} />
                    </div>
                    <span style={{ fontSize: "12px", fontWeight: 600, color: "#94A3B8", width: "32px", textAlign: "right" }}>
                      {subj.pct}%
                    </span>
                  </div>
                </motion.div>
              );
            })
          : [1, 2, 3].map((i) => (
              <div
                key={i}
                style={{ backgroundColor: "#FFFFFF", borderRadius: "16px", padding: "24px", border: "1px solid #E2E8F0" }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: "14px", marginBottom: "14px" }}>
                  <div style={{ width: "48px", height: "48px", borderRadius: "50%", backgroundColor: "#F1F5F9" }} />
                  <div>
                    <div style={{ width: "96px", height: "12px", borderRadius: "4px", backgroundColor: "#F1F5F9", marginBottom: "4px" }} />
                    <div style={{ width: "64px", height: "8px", borderRadius: "4px", backgroundColor: "#F8FAFC" }} />
                  </div>
                </div>
                <div style={{ width: "100%", height: "6px", borderRadius: "4px", backgroundColor: "#F1F5F9" }} />
              </div>
            ))}
      </motion.div>

      {/* Recent Activity */}
      <h2 style={{ fontSize: "18px", fontWeight: 700, color: "#0F172A", marginBottom: "12px", fontFamily: "'Outfit', sans-serif" }}>
        {t("dashboard.recentActivity", "Recent Activity")}
      </h2>
      {recentSessions.length === 0 ? (
        <div style={{ textAlign: "center", padding: "40px 0", borderRadius: "16px", border: "1px solid #E2E8F0", backgroundColor: "#FFFFFF" }}>
          <BookOpen size={40} style={{ margin: "0 auto 12px", color: "#94A3B8", opacity: 0.3 }} />
          <p style={{ fontSize: "14px", fontWeight: 500, color: "#94A3B8", marginBottom: "12px" }}>
            {t("dashboard.emptyState", "Ready to learn something new?")}
          </p>
          <button
            onClick={() => navigate("/map")}
            style={{ padding: "10px 20px", borderRadius: "9999px", backgroundColor: "#F97316", color: "#FFFFFF", fontSize: "14px", fontWeight: 700, cursor: "pointer", border: "none" }}
          >
            {t("dashboard.startLearning", "Start Learning")}
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: "8px" }}>
          {recentSessions.map((session, i) => (
            <div
              key={session.id || i}
              style={{ display: "flex", alignItems: "center", gap: "12px", padding: "12px 16px", borderRadius: "12px", backgroundColor: "#FFFFFF", border: "1px solid #E2E8F0", cursor: "pointer", transition: "box-shadow 0.15s" }}
              onClick={() => {
                if (session.concept_id) {
                  navigate(`/learn/${encodeURIComponent(session.concept_id)}?book_slug=${encodeURIComponent(session.book_slug || "")}`);
                }
              }}
              onMouseEnter={(e) => { e.currentTarget.style.boxShadow = "0 1px 4px rgba(0,0,0,0.06)"; }}
              onMouseLeave={(e) => { e.currentTarget.style.boxShadow = "none"; }}
            >
              {session.phase === "COMPLETED" ? (
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", backgroundColor: "#F0FDF4", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <CheckCircle2 size={14} color="#22C55E" />
                </div>
              ) : (
                <div style={{ width: "28px", height: "28px", borderRadius: "50%", backgroundColor: "#EFF6FF", display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <BookOpen size={14} color="#3B82F6" />
                </div>
              )}
              <div style={{ flex: 1, minWidth: 0 }}>
                <p style={{ fontSize: "14px", fontWeight: 500, color: "#0F172A", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {formatConceptTitle(session.concept_id) || t("dashboard.studySession", "Study session")}
                </p>
                <p style={{ fontSize: "11px", color: "#94A3B8" }}>
                  {session.phase === "COMPLETED" ? t("dashboard.completed", "Completed") : t("dashboard.inProgress", "In progress")}
                  {session.book_slug && ` · ${displayBookTitle(session.book_slug)}`}
                </p>
              </div>
              <ChevronRight size={16} style={{ color: "#94A3B8", opacity: 0.5, flexShrink: 0 }} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
