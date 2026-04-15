import { useState, useEffect } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Trophy, BookOpen, Target, Flame } from "lucide-react";
import { getStudentProgressReport } from "../api/admin";
import BadgeIcon from "../components/game/BadgeIcon";

// ── Constants ─────────────────────────────────────────────────────

const PERIODS = ["day", "week", "month", "all"];

const XP_EVENT_COLORS = {
  card_correct: "bg-green-500",
  concept_mastery: "bg-blue-500",
  mastery_bonus: "bg-[var(--color-primary)]",
  streak_bonus: "bg-orange-500",
  badge_reward: "bg-yellow-500",
};

const XP_DOT_COLORS = {
  card_correct: "bg-green-500",
  concept_mastery: "bg-blue-500",
  mastery_bonus: "bg-[#F97316]",
  streak_bonus: "bg-orange-500",
  badge_reward: "bg-yellow-500",
};

const SUMMARY_CONFIG = [
  { key: "totalXP", Icon: Trophy, bg: "bg-orange-100", text: "text-orange-600", border: "border-t-orange-400" },
  { key: "conceptsMastered", Icon: BookOpen, bg: "bg-blue-100", text: "text-blue-600", border: "border-t-blue-400" },
  { key: "accuracyRate", Icon: Target, bg: "bg-green-100", text: "text-green-600", border: "border-t-green-400" },
  { key: "dailyStreak", Icon: Flame, bg: "bg-red-100", text: "text-red-600", border: "border-t-red-400" },
];

// ── Sub-components ────────────────────────────────────────────────

function SummaryCard({ Icon, bg, text, border, label, value }) {
  return (
    <div
      className={`flex-1 min-w-[140px] rounded-2xl border border-[var(--color-border)] border-t-4 ${border} bg-[var(--color-surface)] p-5 flex flex-col gap-2`}
    >
      <div className={`inline-flex items-center justify-center w-9 h-9 rounded-lg ${bg}`}>
        <Icon size={18} className={text} aria-hidden="true" />
      </div>
      <div className="text-2xl font-bold text-[var(--color-heading)] font-[Outfit,sans-serif] leading-none">
        {value}
      </div>
      <div className="text-xs text-[var(--color-muted)] font-medium">{label}</div>
    </div>
  );
}

function XPBarChart({ dailyXP, t }) {
  if (!dailyXP || dailyXP.length === 0) {
    return (
      <p className="text-[var(--color-muted)] text-sm m-0">
        {t("progress.noXPData", "No XP data for this period.")}
      </p>
    );
  }

  const maxXP = Math.max(...dailyXP.map((d) => d.xp || 0), 1);

  return (
    <div
      className="flex items-end gap-1.5 h-[120px] pb-7 relative overflow-x-auto"
      role="img"
      aria-label={t("progress.xpChartAriaLabel", "Daily XP bar chart")}
    >
      {dailyXP.map((day, idx) => {
        const pct = ((day.xp || 0) / maxXP) * 100;
        const barHeight = Math.max(pct, 2);
        const dateLabel =
          day.date
            ? new Date(day.date).toLocaleDateString(undefined, { month: "short", day: "numeric" })
            : `${idx + 1}`;

        return (
          <div
            key={day.date ?? idx}
            className="flex flex-col items-center gap-1 min-w-[40px] shrink-0"
            title={`${dateLabel}: ${(day.xp || 0).toLocaleString()} XP`}
          >
            <div
              className="w-7 bg-[#F97316] rounded-t transition-[height] duration-300 ease-out self-end min-h-[3px] max-h-[92px]"
              style={{ height: `${barHeight}%` }}
            />
            <span
              className="text-[10px] text-[var(--color-muted)] whitespace-nowrap -rotate-[30deg] origin-[top_center] mt-0.5"
            >
              {dateLabel}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function XPBreakdownList({ breakdown, t }) {
  if (!breakdown || breakdown.length === 0) {
    return (
      <p className="text-[var(--color-muted)] text-sm m-0">
        {t("progress.noBreakdown", "No XP breakdown data.")}
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2.5">
      {breakdown.map((item, idx) => {
        const dotCls = XP_DOT_COLORS[item.event_type] ?? "bg-gray-400";
        const label = t(`progress.eventType.${item.event_type}`, item.event_type ?? "unknown");
        return (
          <div
            key={item.event_type ?? idx}
            className="flex items-center gap-2.5 text-sm"
          >
            <span
              className={`w-2.5 h-2.5 rounded-full ${dotCls} shrink-0`}
              aria-hidden="true"
            />
            <span className="flex-1 text-[var(--color-text)]">{label}</span>
            <span className="font-semibold text-[var(--color-heading)]">
              {(item.xp || 0).toLocaleString()} {t("leaderboard.xpUnit", "XP")}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function BadgesList({ badges, t }) {
  if (!badges || badges.length === 0) {
    return (
      <p className="text-[var(--color-muted)] text-sm m-0">
        {t("progress.noBadges", "No badges earned in this period.")}
      </p>
    );
  }

  return (
    <div className="flex overflow-x-auto gap-3 pb-2">
      {badges.map((badge, idx) => {
        const earnedDate = badge.earned_at
          ? new Date(badge.earned_at).toLocaleDateString()
          : null;
        return (
          <div
            key={badge.badge_key ?? idx}
            className="shrink-0 flex items-center gap-3 px-3 py-2.5 border border-[var(--color-border)] rounded-xl bg-[var(--color-surface)] text-sm"
          >
            <BadgeIcon badgeKey={badge.badge_key} size={20} earned />
            <span className="text-[var(--color-heading)] font-medium whitespace-nowrap">
              {t(`badge.${badge.badge_key}`, badge.badge_key ?? "Badge")}
            </span>
            {earnedDate && (
              <span className="text-xs text-[var(--color-muted)] whitespace-nowrap">{earnedDate}</span>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────

export default function AdminStudentProgressReport() {
  const { t } = useTranslation();
  const { id: studentId } = useParams();
  const navigate = useNavigate();

  const [period, setPeriod] = useState("week");
  const [report, setReport] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    getStudentProgressReport(studentId, period)
      .then((r) => setReport(r.data))
      .catch((e) =>
        setError(
          e.response?.data?.detail ||
            t("progress.loadError", "Failed to load progress report")
        )
      )
      .finally(() => setLoading(false));
  }, [studentId, period]);

  const summary = report?.summary ?? {};
  const dailyXP = report?.daily_xp ?? [];
  const breakdown = report?.xp_breakdown ?? [];
  const badges = report?.badges_earned ?? [];
  const studentName = report?.student_name ?? studentId;

  const accuracyDisplay =
    summary.accuracy_rate != null
      ? `${Math.round(summary.accuracy_rate * 100)}%`
      : summary.accuracy_pct != null
      ? `${Math.round(summary.accuracy_pct)}%`
      : "\u2014";

  const periodLabel = (p) => t(`progress.period.${p}`, p.charAt(0).toUpperCase() + p.slice(1));

  const summaryValues = [
    { label: t("progress.totalXP", "Total XP"), value: (summary.total_xp ?? 0).toLocaleString() },
    { label: t("progress.conceptsMastered", "Concepts Mastered"), value: summary.concepts_mastered ?? 0 },
    { label: t("progress.accuracyRate", "Accuracy Rate"), value: accuracyDisplay },
    { label: t("progress.dailyStreak", "Daily Streak"), value: summary.daily_streak ?? 0 },
  ];

  return (
    <div style={{ maxWidth: "1100px", margin: "0 auto" }}>
      {/* Header */}
      <div className="mb-7">
        <h1 className="text-2xl font-bold text-[var(--color-heading)] font-[Outfit,sans-serif] mb-1">
          {t("progress.title", "Progress Report")}
        </h1>
        {studentName && (
          <p className="text-sm text-[var(--color-muted)]">{studentName}</p>
        )}
      </div>

      {/* Period selector */}
      <div
        className="flex gap-2 mb-7 flex-wrap"
        role="group"
        aria-label={t("progress.periodLabel", "Select time period")}
      >
        {PERIODS.map((p) => {
          const isActive = period === p;
          return (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              aria-pressed={isActive}
              className={`rounded-full px-5 py-2 text-sm font-medium transition-all cursor-pointer ${
                isActive
                  ? "bg-[#F97316] text-white shadow-sm"
                  : "bg-[var(--color-surface)] text-[var(--color-text)] border border-[var(--color-border)] hover:border-[#F97316] hover:text-[#F97316]"
              }`}
            >
              {periodLabel(p)}
            </button>
          );
        })}
      </div>

      {/* Loading */}
      {loading && (
        <div
          className="flex justify-center py-16"
          role="status"
          aria-label={t("common.loading", "Loading...")}
        >
          <div className="w-8 h-8 rounded-full border-3 border-[#F97316] border-t-transparent animate-spin" />
        </div>
      )}

      {/* Error */}
      {!loading && error && (
        <div className="p-3 px-4 bg-red-50 border border-red-200 rounded-2xl text-red-600 text-sm mb-6">
          {error}
        </div>
      )}

      {/* Content */}
      {!loading && !error && report && (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
            {SUMMARY_CONFIG.map((cfg, i) => (
              <SummaryCard
                key={cfg.key}
                Icon={cfg.Icon}
                bg={cfg.bg}
                text={cfg.text}
                border={cfg.border}
                label={summaryValues[i].label}
                value={summaryValues[i].value}
              />
            ))}
          </div>

          {/* XP Trend */}
          <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 mb-6">
            <h2 className="text-base font-bold text-[var(--color-heading)] mb-4">
              {t("progress.xpTrend", "XP Trend")}
            </h2>
            <XPBarChart dailyXP={dailyXP} t={t} />
          </div>

          {/* XP Breakdown */}
          <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6 mb-6">
            <h2 className="text-base font-bold text-[var(--color-heading)] mb-4">
              {t("progress.xpBreakdown", "XP by Activity")}
            </h2>
            <XPBreakdownList breakdown={breakdown} t={t} />
          </div>

          {/* Badges Earned */}
          <div className="rounded-2xl border border-[var(--color-border)] bg-[var(--color-surface)] p-6">
            <h2 className="text-base font-bold text-[var(--color-heading)] mb-4">
              {t("progress.badgesEarned", "Badges Earned")}
            </h2>
            <BadgesList badges={badges} t={t} />
          </div>
        </>
      )}
    </div>
  );
}
