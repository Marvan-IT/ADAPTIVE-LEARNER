import { useState, useEffect, useRef } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../../context/SessionContext";
import { useStudent } from "../../context/StudentContext";
import { useAdaptiveStore } from "../../store/adaptiveStore";
import { getNextConcepts } from "../../api/concepts";
import { formatConceptTitle } from "../../utils/formatConceptTitle";
import { useTranslation } from "react-i18next";
import { trackEvent } from "../../utils/analytics";
import { Check, AlertCircle, Sparkles, RefreshCw, ArrowRight, Trophy } from "lucide-react";
import { motion } from "framer-motion";

// ── Score band ────────────────────────────────────────────────────────────────
// Maps numeric score to: status label + tint color set + the in-page feedback caption.
// Tints come from DashboardPage.jsx STAT_COLORS / SUBJECT_COLORS so this screen
// looks like part of the same app.
function getBand(score, mastered) {
  if (mastered && score >= 90) {
    return {
      key: "excellent",
      label: "Excellent",
      tintBg: "#F0FDF4",          // green tint — Dashboard subject pattern
      tintText: "#15803D",
      barColor: "success",
      Icon: Sparkles,
      caption: "Concept fully mastered — strong work.",
    };
  }
  if (mastered) {
    return {
      key: "passed",
      label: "Mastered",
      tintBg: "#FFF7ED",          // orange tint — primary brand soft
      tintText: "#C2410C",
      barColor: "primary",
      Icon: Check,
      caption: "Passed. Worth a quick review before the next section.",
    };
  }
  return {
    key: "review",
    label: "Review Needed",
    tintBg: "#FFF1F2",            // rose tint — danger soft
    tintText: "#B91C1C",
    barColor: "danger",
    Icon: AlertCircle,
    caption: "This section deserves another pass before moving on.",
  };
}

// Animated horizontal score bar — matches existing ProgressBar visual but
// inlined here so the score number can sit beside the bar at the same baseline.
function ScoreBar({ value, color }) {
  const colorVar =
    color === "success" ? "var(--color-success)" :
    color === "danger"  ? "var(--color-danger)"  :
                          "var(--color-primary-dark)";
  return (
    <div style={{
      flex: 1,
      height: 10,
      backgroundColor: "rgba(15, 23, 42, 0.08)",
      borderRadius: 999,
      overflow: "hidden",
    }}>
      <motion.div
        initial={{ width: 0 }}
        animate={{ width: `${Math.min(Math.max(value, 0), 100)}%` }}
        transition={{ duration: 0.85, delay: 0.25, ease: [0.25, 0.1, 0.25, 1] }}
        style={{ height: "100%", backgroundColor: colorVar, borderRadius: 999 }}
      />
    </div>
  );
}

function StatTile({ value, label, accentColor, delay = 0 }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: [0.25, 0.1, 0.25, 1] }}
      style={{
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: 12,
        padding: "14px 12px",
        textAlign: "center",
      }}
    >
      <div style={{
        fontFamily: "'Outfit', sans-serif",
        fontWeight: 800,
        fontSize: "1.5rem",
        lineHeight: 1.1,
        letterSpacing: "-0.01em",
        fontVariantNumeric: "tabular-nums",
        color: accentColor || "var(--color-text)",
      }}>
        {value}
      </div>
      <div style={{
        fontFamily: "'DM Sans', sans-serif",
        fontSize: "0.6875rem",
        fontWeight: 600,
        letterSpacing: "0.08em",
        textTransform: "uppercase",
        color: "var(--color-text-muted)",
        marginTop: 4,
      }}>
        {label}
      </div>
    </motion.div>
  );
}

export default function CompletionView() {
  const { t } = useTranslation();
  const { score, mastered, conceptTitle, bookTitle, session, dispatch } = useSession();
  const { masteredConcepts } = useStudent();
  const navigate = useNavigate();

  // Pull recent gain values from the adaptive store. lastXpGain is set when
  // award_xp is dispatched; dailyStreak is updated on session completion.
  const lastXpGain = useAdaptiveStore((s) => s.lastXpGain);
  const dailyStreak = useAdaptiveStore((s) => s.dailyStreak);

  const [nextConcept, setNextConcept] = useState(null);
  const [nextLoading, setNextLoading] = useState(true);

  // Fire completion analytic exactly once.
  const trackedRef = useRef(false);
  useEffect(() => {
    if (!trackedRef.current) {
      trackedRef.current = true;
      trackEvent("completion_viewed", {
        score, mastered, concept_id: session?.concept_id, concept_title: conceptTitle,
      });
    }
  }, [score, mastered]);

  // Resolve the next concept via the same /api/v1/concepts/next endpoint the
  // dashboard uses. Returns null when this was the last concept of the book —
  // we render the end-of-book state instead.
  useEffect(() => {
    if (!session?.book_slug) {
      setNextLoading(false);
      return;
    }
    getNextConcepts(masteredConcepts, session.book_slug)
      .then((res) => {
        const ready = (res.data.ready_to_learn || []).filter(
          (c) => c.concept_id !== session.concept_id
        );
        setNextConcept(ready.length > 0 ? ready[0] : null);
      })
      .catch(() => setNextConcept(null))
      .finally(() => setNextLoading(false));
  }, [masteredConcepts, session?.book_slug, session?.concept_id]);

  // Derive time spent if we have started_at on the session. Falls back to "—".
  const timeSpentLabel = (() => {
    const startedAt = session?.started_at;
    if (!startedAt) return "—";
    const startMs = new Date(startedAt).getTime();
    if (isNaN(startMs)) return "—";
    const elapsedSec = Math.max(0, Math.floor((Date.now() - startMs) / 1000));
    if (elapsedSec < 60) return `${elapsedSec}s`;
    const min = Math.floor(elapsedSec / 60);
    return `${min}m`;
  })();

  const xpDisplay = lastXpGain && lastXpGain > 0 ? `+${lastXpGain}` : "—";
  const streakDisplay = dailyStreak > 0 ? `+${dailyStreak}` : "—";

  const band = getBand(score ?? 0, !!mastered);
  const isLastConcept = !nextLoading && mastered && !nextConcept;

  // Section meta line: "Section X.Y · BookTitle" pulled from concept_id.
  const sectionLabel = (() => {
    const cid = session?.concept_id || "";
    const m = cid.match(/(\d+\.\d+)$/);
    return m ? `Section ${m[1]}` : "";
  })();

  // ── Action handlers ────────────────────────────────────────────────────────
  const handleNext = () => {
    if (!nextConcept) return;
    trackEvent("completion_action", {
      action: "next_concept",
      concept_id: session?.concept_id, concept_title: conceptTitle,
      next_concept_id: nextConcept.concept_id,
      next_concept_title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id),
    });
    dispatch({ type: "SESSION_COMPLETED" });
    navigate(`/learn/${encodeURIComponent(nextConcept.concept_id)}`);
  };

  const handleRetry = () => {
    trackEvent("completion_action", {
      action: "try_again", concept_id: session?.concept_id, concept_title: conceptTitle,
    });
    dispatch({ type: "SESSION_COMPLETED" });
    window.location.reload();
  };

  const handleBackToMap = () => {
    trackEvent("completion_action", {
      action: "back_to_map", concept_id: session?.concept_id, concept_title: conceptTitle,
    });
    dispatch({ type: "SESSION_COMPLETED" });
    navigate("/map");
  };

  const BadgeIcon = band.Icon;

  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.4, ease: [0.25, 0.1, 0.25, 1] }}
      style={{
        maxWidth: 720,
        margin: "0 auto",
        backgroundColor: "var(--color-surface)",
        border: "1px solid var(--color-border)",
        borderRadius: 16,
        padding: "28px 28px 24px",
        boxShadow: "0 1px 2px rgba(15, 23, 42, 0.04)",
      }}
    >
      {/* ── Header row: concept name + status badge ───────────────────────── */}
      <div style={{
        display: "flex",
        alignItems: "flex-start",
        justifyContent: "space-between",
        gap: 16,
        marginBottom: 22,
      }}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <h1 style={{
            fontFamily: "'Outfit', sans-serif",
            fontWeight: 800,
            fontSize: "1.875rem",
            lineHeight: 1.15,
            letterSpacing: "-0.02em",
            color: "var(--color-text)",
            margin: "0 0 4px 0",
          }}>
            {conceptTitle || formatConceptTitle(session?.concept_id || "")}
          </h1>
          {(sectionLabel || bookTitle) && (
            <p style={{
              fontFamily: "'DM Sans', sans-serif",
              fontSize: "0.875rem",
              fontWeight: 500,
              color: "var(--color-text-muted)",
              margin: 0,
            }}>
              {sectionLabel}
              {sectionLabel && bookTitle && (
                <span style={{ margin: "0 8px", opacity: 0.5 }}>·</span>
              )}
              {bookTitle}
            </p>
          )}
        </div>

        <div style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          padding: "6px 12px",
          borderRadius: 999,
          fontFamily: "'Outfit', sans-serif",
          fontSize: "0.6875rem",
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          whiteSpace: "nowrap",
          flexShrink: 0,
          backgroundColor: band.tintBg,
          color: band.tintText,
        }}>
          <BadgeIcon size={13} strokeWidth={2.8} />
          {band.label}
        </div>
      </div>

      {/* ── Score block (tinted by band) ──────────────────────────────────── */}
      <div style={{
        backgroundColor: band.tintBg,
        borderRadius: 12,
        padding: "18px 20px",
        marginBottom: 20,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <ScoreBar value={score ?? 0} color={band.barColor} />
          <div style={{
            fontFamily: "'Outfit', sans-serif",
            fontWeight: 700,
            fontSize: "1.625rem",
            lineHeight: 1,
            letterSpacing: "-0.02em",
            fontVariantNumeric: "tabular-nums",
            color: "var(--color-text)",
            whiteSpace: "nowrap",
          }}>
            {score ?? 0}
            <span style={{
              fontWeight: 500,
              fontSize: "1rem",
              color: "var(--color-text-muted)",
              marginLeft: 2,
            }}>
              / 100
            </span>
          </div>
        </div>
        <p style={{
          marginTop: 10,
          marginBottom: 0,
          fontFamily: "'DM Sans', sans-serif",
          fontSize: "0.875rem",
          color: "var(--color-text-muted)",
          fontWeight: 500,
        }}>
          {band.caption}
        </p>
      </div>

      {/* ── Stat tiles (XP earned · time spent · streak) ─────────────────── */}
      <div style={{
        display: "grid",
        gridTemplateColumns: "repeat(3, 1fr)",
        gap: 10,
        marginBottom: 22,
      }}>
        <StatTile value={xpDisplay} label={t("completion.xpEarned", "XP Earned")}    accentColor="var(--color-primary-dark)" delay={0.45} />
        <StatTile value={timeSpentLabel} label={t("completion.timeSpent", "Time Spent")} delay={0.55} />
        <StatTile value={streakDisplay} label={t("completion.dayStreak", "Day Streak")} accentColor="#B45309" delay={0.65} />
      </div>

      {/* ── Actions ──────────────────────────────────────────────────────── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10, alignItems: "stretch" }}>
        {/* Primary CTA varies by state */}
        {!mastered && (
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.98 }}
            onClick={handleRetry}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              width: "100%", height: 48,
              border: "none", borderRadius: 10,
              backgroundColor: "#B91C1C",
              color: "white",
              fontFamily: "'DM Sans', sans-serif",
              fontSize: "0.9375rem",
              fontWeight: 700,
              letterSpacing: "-0.01em",
              cursor: "pointer",
              boxShadow: "0 1px 2px rgba(185, 28, 28, 0.18)",
            }}
          >
            <RefreshCw size={18} strokeWidth={2.4} />
            {t("completion.tryAgain", "Read this section again")}
          </motion.button>
        )}

        {mastered && nextConcept && (
          <motion.button
            whileHover={{ scale: 1.01 }}
            whileTap={{ scale: 0.98 }}
            onClick={handleNext}
            style={{
              display: "flex", alignItems: "center", justifyContent: "center", gap: 8,
              width: "100%", height: 48,
              border: "none", borderRadius: 10,
              backgroundColor: "var(--color-primary-dark)",
              color: "white",
              fontFamily: "'DM Sans', sans-serif",
              fontSize: "0.9375rem",
              fontWeight: 700,
              letterSpacing: "-0.01em",
              cursor: "pointer",
              boxShadow: "0 1px 2px rgba(234, 88, 12, 0.20)",
            }}
          >
            {t("completion.next", { title: nextConcept.concept_title || formatConceptTitle(nextConcept.concept_id) })}
            <ArrowRight size={18} strokeWidth={2.4} />
          </motion.button>
        )}

        {/* End-of-book state: mastered but no next concept available */}
        {isLastConcept && (
          <div style={{
            display: "flex", flexDirection: "column", alignItems: "center", gap: 6,
            padding: "10px 0 4px",
          }}>
            <Trophy size={28} color="var(--color-primary-dark)" strokeWidth={2.2} />
            <p style={{
              fontFamily: "'Outfit', sans-serif",
              fontWeight: 700,
              fontSize: "1.0625rem",
              color: "var(--color-text)",
              margin: 0,
              textAlign: "center",
            }}>
              {t("completion.bookComplete", "You've completed the book!")}
            </p>
            <p style={{
              fontFamily: "'DM Sans', sans-serif",
              fontSize: "0.875rem",
              color: "var(--color-text-muted)",
              margin: 0,
              textAlign: "center",
            }}>
              {t("completion.bookCompleteSub", "Every section mastered. Pick another book to continue learning.")}
            </p>
          </div>
        )}

        <motion.button
          whileHover={{ scale: 1.005 }}
          whileTap={{ scale: 0.99 }}
          onClick={handleBackToMap}
          style={{
            alignSelf: "center",
            padding: "8px 16px",
            backgroundColor: "transparent",
            border: "none",
            fontFamily: "'DM Sans', sans-serif",
            fontSize: "0.875rem",
            fontWeight: 500,
            color: "var(--color-text-muted)",
            cursor: "pointer",
          }}
        >
          {t("learning.backToMap", "Back to Concept Map")}
        </motion.button>
      </div>
    </motion.div>
  );
}
