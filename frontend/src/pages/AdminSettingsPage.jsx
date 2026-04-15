import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { getAdminConfig, updateAdminConfig } from "../api/admin";
import { BookOpen, Trophy, Flame, ToggleLeft, Cpu } from "lucide-react";

const GROUP_ICONS = {
  learning: BookOpen,
  xp: Trophy,
  streaks: Flame,
  flags: ToggleLeft,
  ai: Cpu,
};

const SETTING_GROUPS = [
  {
    key: "learning",
    titleKey: "admin.settings.group.learning",
    titleDefault: "Learning & Mastery",
    settings: [
      {
        key: "CHUNK_EXAM_PASS_RATE",
        type: "number",
        defaultValue: 0.5,
        step: 0.01,
        descKey: "admin.settings.desc.chunkExamPassRate",
        descDefault: "Exam pass rate (0.0-1.0)",
        labelKey: "admin.settings.label.chunkExamPassRate",
        labelDefault: "CHUNK_EXAM_PASS_RATE",
      },
    ],
  },
  {
    key: "xp",
    titleKey: "admin.settings.group.xp",
    titleDefault: "XP & Gamification",
    settings: [
      {
        key: "XP_MASTERY",
        type: "number",
        defaultValue: 50,
        step: 1,
        descKey: "admin.settings.desc.xpMastery",
        descDefault: "XP awarded for mastering a concept",
        labelKey: "admin.settings.label.xpMastery",
        labelDefault: "XP_MASTERY",
      },
      {
        key: "XP_MASTERY_BONUS",
        type: "number",
        defaultValue: 25,
        step: 1,
        descKey: "admin.settings.desc.xpMasteryBonus",
        descDefault: "Bonus XP for high scores",
        labelKey: "admin.settings.label.xpMasteryBonus",
        labelDefault: "XP_MASTERY_BONUS",
      },
      {
        key: "XP_CONSOLATION",
        type: "number",
        defaultValue: 10,
        step: 1,
        descKey: "admin.settings.desc.xpConsolation",
        descDefault: "Consolation XP without mastery",
        labelKey: "admin.settings.label.xpConsolation",
        labelDefault: "XP_CONSOLATION",
      },
      {
        key: "XP_PER_DIFFICULTY_POINT",
        type: "number",
        defaultValue: 4,
        step: 1,
        descKey: "admin.settings.desc.xpPerDifficulty",
        descDefault: "XP per difficulty point (base = difficulty x this value)",
        labelKey: "admin.settings.label.xpPerDifficulty",
        labelDefault: "XP_PER_DIFFICULTY_POINT",
      },
      {
        key: "XP_HINT_PENALTY",
        type: "number",
        defaultValue: 0.25,
        step: 0.05,
        descKey: "admin.settings.desc.xpHintPenalty",
        descDefault: "XP reduction per hint used (0.25 = 25% per hint)",
        labelKey: "admin.settings.label.xpHintPenalty",
        labelDefault: "XP_HINT_PENALTY",
      },
      {
        key: "XP_WRONG_PENALTY",
        type: "number",
        defaultValue: 0.15,
        step: 0.05,
        descKey: "admin.settings.desc.xpWrongPenalty",
        descDefault: "XP reduction per wrong attempt (0.15 = 15% per attempt)",
        labelKey: "admin.settings.label.xpWrongPenalty",
        labelDefault: "XP_WRONG_PENALTY",
      },
      {
        key: "XP_FIRST_ATTEMPT_BONUS",
        type: "number",
        defaultValue: 1.5,
        step: 0.1,
        descKey: "admin.settings.desc.xpFirstAttemptBonus",
        descDefault: "Multiplier for first-attempt correct answers (no hints, no wrong attempts)",
        labelKey: "admin.settings.label.xpFirstAttemptBonus",
        labelDefault: "XP_FIRST_ATTEMPT_BONUS",
      },
    ],
  },
  {
    key: "streaks",
    titleKey: "admin.settings.group.streaks",
    titleDefault: "Streak Tiers",
    settings: [
      {
        key: "STREAK_TIER_1_DAYS",
        type: "number",
        defaultValue: 3,
        step: 1,
        descKey: "admin.settings.desc.streakTier1Days",
        descDefault: "Days for streak tier 1",
        labelKey: "admin.settings.label.streakTier1Days",
        labelDefault: "STREAK_TIER_1_DAYS",
      },
      {
        key: "STREAK_TIER_1_MULT",
        type: "number",
        defaultValue: 1.25,
        step: 0.05,
        descKey: "admin.settings.desc.streakTier1Mult",
        descDefault: "XP multiplier for streak tier 1",
        labelKey: "admin.settings.label.streakTier1Mult",
        labelDefault: "STREAK_TIER_1_MULT",
      },
      {
        key: "STREAK_TIER_2_DAYS",
        type: "number",
        defaultValue: 5,
        step: 1,
        descKey: "admin.settings.desc.streakTier2Days",
        descDefault: "Days for streak tier 2",
        labelKey: "admin.settings.label.streakTier2Days",
        labelDefault: "STREAK_TIER_2_DAYS",
      },
      {
        key: "STREAK_TIER_2_MULT",
        type: "number",
        defaultValue: 1.5,
        step: 0.05,
        descKey: "admin.settings.desc.streakTier2Mult",
        descDefault: "XP multiplier for streak tier 2",
        labelKey: "admin.settings.label.streakTier2Mult",
        labelDefault: "STREAK_TIER_2_MULT",
      },
      {
        key: "STREAK_TIER_3_DAYS",
        type: "number",
        defaultValue: 7,
        step: 1,
        descKey: "admin.settings.desc.streakTier3Days",
        descDefault: "Days for streak tier 3",
        labelKey: "admin.settings.label.streakTier3Days",
        labelDefault: "STREAK_TIER_3_DAYS",
      },
      {
        key: "STREAK_TIER_3_MULT",
        type: "number",
        defaultValue: 2.0,
        step: 0.1,
        descKey: "admin.settings.desc.streakTier3Mult",
        descDefault: "XP multiplier for streak tier 3",
        labelKey: "admin.settings.label.streakTier3Mult",
        labelDefault: "STREAK_TIER_3_MULT",
      },
      {
        key: "STREAK_TIER_4_DAYS",
        type: "number",
        defaultValue: 14,
        step: 1,
        descKey: "admin.settings.desc.streakTier4Days",
        descDefault: "Days for streak tier 4",
        labelKey: "admin.settings.label.streakTier4Days",
        labelDefault: "STREAK_TIER_4_DAYS",
      },
      {
        key: "STREAK_TIER_4_MULT",
        type: "number",
        defaultValue: 2.5,
        step: 0.1,
        descKey: "admin.settings.desc.streakTier4Mult",
        descDefault: "XP multiplier for streak tier 4",
        labelKey: "admin.settings.label.streakTier4Mult",
        labelDefault: "STREAK_TIER_4_MULT",
      },
    ],
  },
  {
    key: "flags",
    titleKey: "admin.settings.group.flags",
    titleDefault: "Feature Flags",
    settings: [
      {
        key: "GAMIFICATION_ENABLED",
        type: "toggle",
        defaultValue: true,
        descKey: "admin.settings.desc.gamificationEnabled",
        descDefault: "Master switch for gamification system",
        labelKey: "admin.settings.label.gamificationEnabled",
        labelDefault: "GAMIFICATION_ENABLED",
      },
      {
        key: "LEADERBOARD_ENABLED",
        type: "toggle",
        defaultValue: false,
        descKey: "admin.settings.desc.leaderboardEnabled",
        descDefault: "Show leaderboard to students",
        labelKey: "admin.settings.label.leaderboardEnabled",
        labelDefault: "LEADERBOARD_ENABLED",
      },
      {
        key: "BADGES_ENABLED",
        type: "toggle",
        defaultValue: true,
        descKey: "admin.settings.desc.badgesEnabled",
        descDefault: "Enable badge awards",
        labelKey: "admin.settings.label.badgesEnabled",
        labelDefault: "BADGES_ENABLED",
      },
      {
        key: "STREAK_MULTIPLIER_ENABLED",
        type: "toggle",
        defaultValue: true,
        descKey: "admin.settings.desc.streakMultiplierEnabled",
        descDefault: "Apply streak multiplier to XP",
        labelKey: "admin.settings.label.streakMultiplierEnabled",
        labelDefault: "STREAK_MULTIPLIER_ENABLED",
      },
    ],
  },
  {
    key: "ai",
    titleKey: "admin.settings.group.ai",
    titleDefault: "AI Models",
    settings: [
      {
        key: "OPENAI_MODEL",
        type: "text",
        defaultValue: "gpt-4o",
        descKey: "admin.settings.desc.openaiModel",
        descDefault: "Primary AI model",
        labelKey: "admin.settings.label.openaiModel",
        labelDefault: "OPENAI_MODEL",
      },
      {
        key: "OPENAI_MODEL_MINI",
        type: "text",
        defaultValue: "gpt-4o-mini",
        descKey: "admin.settings.desc.openaiModelMini",
        descDefault: "Lightweight AI model",
        labelKey: "admin.settings.label.openaiModelMini",
        labelDefault: "OPENAI_MODEL_MINI",
      },
    ],
  },
];

const ALL_SETTINGS = SETTING_GROUPS.flatMap((g) => g.settings);

function buildInitialForm(config) {
  const form = {};
  for (const s of ALL_SETTINGS) {
    const raw = config?.[s.key];
    form[s.key] = raw !== undefined && raw !== null ? raw : s.defaultValue;
  }
  return form;
}

const cardStyle = {
  borderRadius: "12px",
  border: "1px solid #E2E8F0",
  backgroundColor: "#FFFFFF",
  padding: "24px",
  marginBottom: "24px",
  boxShadow: "0 1px 2px rgba(0,0,0,0.04)",
};

const sectionHeaderStyle = {
  display: "flex",
  alignItems: "center",
  gap: "10px",
  marginBottom: "20px",
  paddingBottom: "16px",
  borderBottom: "1px solid #F1F5F9",
};

const inputFieldStyle = {
  borderRadius: "12px",
  border: "1px solid #E2E8F0",
  height: "44px",
  padding: "0 16px",
  fontSize: "14px",
  width: "120px",
  textAlign: "right",
  color: "#0F172A",
  backgroundColor: "#FFFFFF",
  outline: "none",
};

const textInputStyle = {
  ...inputFieldStyle,
  width: "200px",
  textAlign: "left",
  fontFamily: "monospace",
};

const descStyle = {
  fontSize: "13px",
  color: "#94A3B8",
  marginTop: "2px",
};

const saveBtnStyle = {
  borderRadius: "9999px",
  backgroundColor: "#EA580C",
  color: "#FFFFFF",
  padding: "10px 24px",
  fontSize: "14px",
  fontWeight: 600,
  border: "none",
  cursor: "pointer",
  transition: "background-color 150ms ease",
};

const saveBtnDisabled = {
  ...saveBtnStyle,
  opacity: 0.5,
  cursor: "not-allowed",
};

function ToggleSwitch({ checked, onChange }) {
  const isOn = checked === "true" || checked === true;
  return (
    <button
      type="button"
      onClick={() => onChange(isOn ? "false" : "true")}
      style={{
        position: "relative",
        display: "inline-flex",
        height: "28px",
        width: "52px",
        flexShrink: 0,
        cursor: "pointer",
        borderRadius: "9999px",
        border: "2px solid transparent",
        backgroundColor: isOn ? "#EA580C" : "#CBD5E1",
        transition: "background-color 200ms ease",
        padding: 0,
        outline: "none",
      }}
      role="switch"
      aria-checked={isOn}
    >
      <span
        style={{
          pointerEvents: "none",
          display: "inline-block",
          height: "24px",
          width: "24px",
          borderRadius: "9999px",
          backgroundColor: "#FFFFFF",
          boxShadow: "0 1px 3px rgba(0,0,0,0.2)",
          transition: "transform 200ms ease",
          transform: isOn ? "translateX(24px)" : "translateX(0px)",
        }}
      />
    </button>
  );
}

export default function AdminSettingsPage() {
  const { t } = useTranslation();

  const [loadedConfig, setLoadedConfig] = useState(null);
  const [formValues, setFormValues] = useState(() => buildInitialForm(null));
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [saving, setSaving] = useState(false);
  const [successMsg, setSuccessMsg] = useState(null);
  const [saveError, setSaveError] = useState(null);

  useEffect(() => {
    getAdminConfig()
      .then((r) => {
        setLoadedConfig(r.data);
        setFormValues(buildInitialForm(r.data));
      })
      .catch((e) =>
        setError(e.response?.data?.detail || t("admin.settings.loadError", "Failed to load settings"))
      )
      .finally(() => setLoading(false));
  }, []);

  const handleChange = (key, value) => {
    setFormValues((prev) => ({ ...prev, [key]: value }));
    setSuccessMsg(null);
    setSaveError(null);
  };

  const handleSave = () => {
    if (!loadedConfig) return;

    const diff = {};
    for (const s of ALL_SETTINGS) {
      const current = formValues[s.key];
      const original = loadedConfig[s.key] !== undefined && loadedConfig[s.key] !== null
        ? loadedConfig[s.key]
        : s.defaultValue;

      const coercedCurrent = s.type === "number" ? Number(current) : current;
      const coercedOriginal = s.type === "number" ? Number(original) : original;

      if (coercedCurrent !== coercedOriginal) {
        diff[s.key] = coercedCurrent;
      }
    }

    if (Object.keys(diff).length === 0) {
      setSuccessMsg(t("admin.settings.noChanges", "No changes to save."));
      return;
    }

    setSaving(true);
    setSaveError(null);
    setSuccessMsg(null);

    updateAdminConfig(diff)
      .then(() => {
        setLoadedConfig((prev) => ({ ...prev, ...diff }));
        setSuccessMsg(t("admin.settings.saved", "Settings saved successfully."));
      })
      .catch((e) =>
        setSaveError(e.response?.data?.detail || t("admin.settings.saveError", "Failed to save settings"))
      )
      .finally(() => setSaving(false));
  };

  return (
    <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
      {/* Header */}
      <div style={{ marginBottom: "24px" }}>
        <h1 style={{ fontSize: "24px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", margin: "0 0 4px 0" }}>
          {t("admin.settings.title", "Settings")}
        </h1>
        <p style={{ fontSize: "14px", color: "#94A3B8", margin: 0 }}>
          {t(
            "admin.settings.description",
            "Configure global platform parameters. Changes take effect on next session."
          )}
        </p>
      </div>

      {/* Loading */}
      {loading && (
        <div style={{ color: "#94A3B8", fontSize: "14px" }}>
          {t("admin.loading", "Loading...")}
        </div>
      )}

      {/* Load Error */}
      {error && (
        <div style={{
          marginBottom: "24px",
          padding: "12px 16px",
          borderRadius: "12px",
          backgroundColor: "#FEF2F2",
          border: "1px solid #FECACA",
          color: "#DC2626",
          fontSize: "14px",
        }}>
          {error}
        </div>
      )}

      {!loading && !error && (
        <div>
          {/* Settings Groups */}
          {SETTING_GROUPS.map((group) => {
            const Icon = GROUP_ICONS[group.key] || BookOpen;
            return (
              <section key={group.key} style={cardStyle}>
                {/* Section header */}
                <div style={sectionHeaderStyle}>
                  <Icon size={18} style={{ color: "#EA580C" }} />
                  <h2 style={{ fontSize: "16px", fontWeight: 700, color: "#0F172A", fontFamily: "'Outfit', sans-serif", margin: 0 }}>
                    {t(group.titleKey, group.titleDefault)}
                  </h2>
                </div>

                {/* Settings rows */}
                <div>
                  {group.settings.map((setting, idx) => (
                    <div
                      key={setting.key}
                      style={{
                        display: "flex",
                        alignItems: "center",
                        gap: "16px",
                        padding: "12px 0",
                        borderTop: idx > 0 ? "1px solid #F1F5F9" : "none",
                      }}
                    >
                      {/* Label + Description */}
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontSize: "14px", color: "#334155", fontWeight: 500, fontFamily: "monospace", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                          {t(setting.labelKey, setting.labelDefault)}
                        </div>
                        <div style={descStyle}>
                          {t(setting.descKey, setting.descDefault)}
                        </div>
                      </div>

                      {/* Input */}
                      {setting.type === "toggle" ? (
                        <ToggleSwitch
                          checked={formValues[setting.key]}
                          onChange={(val) => handleChange(setting.key, val)}
                        />
                      ) : (
                        <input
                          type={setting.type}
                          step={setting.step}
                          value={formValues[setting.key]}
                          onChange={(e) => handleChange(setting.key, e.target.value)}
                          style={setting.type === "text" ? textInputStyle : inputFieldStyle}
                        />
                      )}
                    </div>
                  ))}
                </div>
              </section>
            );
          })}

          {/* Feedback messages */}
          {successMsg && (
            <div style={{
              padding: "12px 16px",
              borderRadius: "12px",
              backgroundColor: "#F0FDF4",
              border: "1px solid #BBF7D0",
              color: "#16A34A",
              fontSize: "14px",
              marginBottom: "16px",
            }}>
              {successMsg}
            </div>
          )}

          {saveError && (
            <div style={{
              padding: "12px 16px",
              borderRadius: "12px",
              backgroundColor: "#FEF2F2",
              border: "1px solid #FECACA",
              color: "#DC2626",
              fontSize: "14px",
              marginBottom: "16px",
            }}>
              {saveError}
            </div>
          )}

          {/* Save Button */}
          <button
            onClick={handleSave}
            disabled={saving}
            style={saving ? saveBtnDisabled : saveBtnStyle}
          >
            {saving
              ? t("admin.settings.saving", "Saving...")
              : t("admin.settings.save", "Save Settings")}
          </button>
        </div>
      )}
    </div>
  );
}
