import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { motion } from "framer-motion";
import { Trophy, Star, Flame, Target, Lock } from "lucide-react";
import { useStudent } from "../context/StudentContext";
import { useAdaptiveStore } from "../store/adaptiveStore";
import { getStudentBadges } from "../api/students";
import { EmptyState } from "../components/ui";
import { staggerContainer, staggerItem } from "../theme/themes";

const BADGE_CATEGORIES = [
  {
    id: "learning",
    label: "Learning Milestones",
    labelKey: "achievements.categoryLearning",
    icon: Star,
    color: "#D97706",
    bgColor: "#FFFBEB",
    badges: ["first_correct", "first_mastery", "mastery_5", "mastery_10", "mastery_25"],
  },
  {
    id: "streaks",
    label: "Streak Champions",
    labelKey: "achievements.categoryStreaks",
    icon: Flame,
    color: "#EA580C",
    bgColor: "#FFF7ED",
    badges: ["streak_3", "streak_7", "streak_14", "streak_30"],
  },
  {
    id: "performance",
    label: "Performance Stars",
    labelKey: "achievements.categoryPerformance",
    icon: Target,
    color: "#16A34A",
    bgColor: "#F0FDF4",
    badges: ["correct_10", "correct_25", "perfect_chunk", "speed_demon"],
  },
];

const BADGE_META = {
  first_correct: { nameKey: "badge.first_correct", name: "First Correct", descKey: "badge.first_correct_desc", desc: "Answer your first question correctly" },
  first_mastery: { nameKey: "badge.first_mastery", name: "First Mastery", descKey: "badge.first_mastery_desc", desc: "Master your first concept" },
  mastery_5: { nameKey: "badge.mastery_5", name: "5 Concepts", descKey: "badge.mastery_5_desc", desc: "Master 5 concepts" },
  mastery_10: { nameKey: "badge.mastery_10", name: "10 Concepts", descKey: "badge.mastery_10_desc", desc: "Master 10 concepts" },
  mastery_25: { nameKey: "badge.mastery_25", name: "25 Concepts", descKey: "badge.mastery_25_desc", desc: "Master 25 concepts" },
  streak_3: { nameKey: "badge.streak_3", name: "3-Day Streak", descKey: "badge.streak_3_desc", desc: "Learn 3 days in a row" },
  streak_7: { nameKey: "badge.streak_7", name: "7-Day Streak", descKey: "badge.streak_7_desc", desc: "Learn 7 days in a row" },
  streak_14: { nameKey: "badge.streak_14", name: "14-Day Streak", descKey: "badge.streak_14_desc", desc: "Learn 14 days in a row" },
  streak_30: { nameKey: "badge.streak_30", name: "30-Day Streak", descKey: "badge.streak_30_desc", desc: "Learn 30 days in a row" },
  correct_10: { nameKey: "badge.correct_10", name: "10 Correct", descKey: "badge.correct_10_desc", desc: "Answer 10 questions correctly" },
  correct_25: { nameKey: "badge.correct_25", name: "25 Correct", descKey: "badge.correct_25_desc", desc: "Answer 25 questions correctly" },
  perfect_chunk: { nameKey: "badge.perfect_chunk", name: "Perfect Section", descKey: "badge.perfect_chunk_desc", desc: "Complete a section with no mistakes" },
  speed_demon: { nameKey: "badge.speed_demon", name: "Speed Demon", descKey: "badge.speed_demon_desc", desc: "Complete a card in under 15 seconds" },
};

export default function AchievementsPage() {
  const { t } = useTranslation();
  const { student } = useStudent();
  const storeBadges = useAdaptiveStore((s) => s.badges);
  const [apiBadges, setApiBadges] = useState([]);

  useEffect(() => {
    if (student?.id) {
      getStudentBadges(student.id)
        .then((res) => setApiBadges(res.data?.badges || res.data || []))
        .catch(() => {});
    }
  }, [student?.id]);

  const earnedSet = new Set([
    ...(storeBadges || []).map((b) => b.badge_type || b.type || b),
    ...apiBadges.map((b) => b.badge_type || b.type || b),
  ]);

  const allBadgeIds = BADGE_CATEGORIES.flatMap((c) => c.badges);
  const totalCount = allBadgeIds.length;
  const earnedCount = allBadgeIds.filter((id) => earnedSet.has(id)).length;
  const pct = totalCount > 0 ? Math.round((earnedCount / totalCount) * 100) : 0;

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "24px" }}>
      <div>
        {/* Header */}
        <div
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "flex-start",
            marginBottom: "32px",
          }}
        >
          <h1
            style={{
              fontFamily: "'Outfit', sans-serif",
              fontWeight: 700,
              fontSize: "1.875rem",
              color: "#0F172A",
              margin: 0,
            }}
          >
            {t("achievements.title", "Your Achievements")} 🏆
          </h1>
          <div style={{ display: "flex", gap: "16px" }}>
            <div
              style={{
                backgroundColor: "#FFFFFF",
                borderRadius: "16px",
                padding: "12px 20px",
                border: "1px solid #E2E8F0",
                textAlign: "center",
              }}
            >
              <p
                style={{
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  color: "#F97316",
                  margin: 0,
                }}
              >
                {earnedCount}
              </p>
              <p
                style={{
                  fontSize: "0.75rem",
                  color: "#94A3B8",
                  margin: 0,
                }}
              >
                {t("achievements.earned", "Earned")}
              </p>
            </div>
            <div
              style={{
                backgroundColor: "#FFFFFF",
                borderRadius: "16px",
                padding: "12px 20px",
                border: "1px solid #E2E8F0",
                textAlign: "center",
              }}
            >
              <p
                style={{
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  color: "#0F172A",
                  margin: 0,
                }}
              >
                {totalCount}
              </p>
              <p
                style={{
                  fontSize: "0.75rem",
                  color: "#94A3B8",
                  margin: 0,
                }}
              >
                {t("achievements.total", "Total")}
              </p>
            </div>
            <div
              style={{
                backgroundColor: "#FFFFFF",
                borderRadius: "16px",
                padding: "12px 20px",
                border: "1px solid #E2E8F0",
                textAlign: "center",
              }}
            >
              <p
                style={{
                  fontSize: "1.5rem",
                  fontWeight: 700,
                  color: "#16A34A",
                  margin: 0,
                }}
              >
                {pct}%
              </p>
              <p
                style={{
                  fontSize: "0.75rem",
                  color: "#94A3B8",
                  margin: 0,
                }}
              >
                {t("achievements.complete", "Complete")}
              </p>
            </div>
          </div>
        </div>

        {/* Categories */}
        {BADGE_CATEGORIES.map((cat) => (
          <div key={cat.id} style={{ marginBottom: "32px" }}>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                marginBottom: "16px",
              }}
            >
              <cat.icon size={20} style={{ color: cat.color }} />
              <h2
                style={{
                  fontFamily: "'Outfit', sans-serif",
                  fontWeight: 700,
                  fontSize: "1.125rem",
                  color: "#0F172A",
                  margin: 0,
                }}
              >
                {t(cat.labelKey, cat.label)}
              </h2>
            </div>
            <motion.div
              variants={staggerContainer}
              initial="hidden"
              animate="show"
              style={{
                display: "grid",
                gridTemplateColumns: "repeat(auto-fill, minmax(160px, 1fr))",
                gap: "16px",
              }}
            >
              {cat.badges.map((badgeId) => {
                const earned = earnedSet.has(badgeId);
                const meta = BADGE_META[badgeId] || { name: badgeId, desc: "" };
                return (
                  <motion.div
                    key={badgeId}
                    variants={staggerItem}
                    style={{
                      borderRadius: "16px",
                      padding: "16px",
                      border: earned ? "1px solid transparent" : "1px solid #E2E8F0",
                      textAlign: "center",
                      backgroundColor: earned ? cat.bgColor : "#FAFAFA",
                      opacity: earned ? 1 : 0.6,
                      transition: "transform 150ms ease",
                    }}
                    whileHover={earned ? { y: -2 } : undefined}
                  >
                    <div
                      style={{
                        width: "64px",
                        height: "64px",
                        borderRadius: "50%",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        margin: "0 auto 12px auto",
                        backgroundColor: earned ? "rgba(255,255,255,0.7)" : "#E2E8F0",
                        boxShadow: earned ? "0 1px 3px rgba(0,0,0,0.1)" : "none",
                      }}
                    >
                      {earned ? (
                        <cat.icon size={28} style={{ color: cat.color }} />
                      ) : (
                        <Lock size={20} style={{ color: "#94A3B8" }} />
                      )}
                    </div>
                    <p
                      style={{
                        fontSize: "0.875rem",
                        fontWeight: 600,
                        marginBottom: "4px",
                        margin: "0 0 4px 0",
                        color: earned ? "#0F172A" : "#94A3B8",
                      }}
                    >
                      {t(meta.nameKey, meta.name)}
                    </p>
                    <p
                      style={{
                        fontSize: "11px",
                        color: "#94A3B8",
                        lineHeight: 1.4,
                        margin: 0,
                      }}
                    >
                      {t(meta.descKey, meta.desc)}
                    </p>
                    {earned && (
                      <p
                        style={{
                          fontSize: "10px",
                          color: "#16A34A",
                          fontWeight: 500,
                          marginTop: "8px",
                          marginBottom: 0,
                        }}
                      >
                        ✓ {t("achievements.badgeEarned", "Earned")}
                      </p>
                    )}
                  </motion.div>
                );
              })}
            </motion.div>
          </div>
        ))}

        {earnedCount === 0 && (
          <EmptyState
            icon={<Trophy size={64} style={{ color: "#94A3B8" }} />}
            title={t("achievements.emptyTitle", "No badges yet!")}
            description={t("achievements.emptyDesc", "Complete lessons to earn badges and track your progress.")}
          />
        )}
      </div>
    </div>
  );
}
