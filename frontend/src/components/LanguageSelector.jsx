import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { LANGUAGES } from "../i18n";
import { useStudent } from "../context/StudentContext";
import { useSession } from "../context/SessionContext";
import { updateLanguage } from "../api/students";
import { Globe, Search, Check, ChevronDown } from "lucide-react";
import { trackEvent } from "../utils/analytics";
import LanguageChangeOverlay from "./LanguageChangeOverlay";

export default function LanguageSelector({ compact = false, prominent = false }) {
  const { i18n, t } = useTranslation();
  const { student } = useStudent();
  const { dispatch: sessionDispatch, reloadCurrentChunk } = useSession();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlightIdx, setHighlightIdx] = useState(0);
  const [changingLang, setChangingLang] = useState(null);
  const [apiDone, setApiDone] = useState(false);
  const containerRef = useRef(null);
  const searchRef = useRef(null);
  const listRef = useRef(null);

  const currentLang = LANGUAGES.find((l) => l.code === i18n.language) || LANGUAGES[0];

  const filtered = LANGUAGES.filter((l) => {
    const q = search.toLowerCase();
    return (
      l.name.toLowerCase().includes(q) ||
      l.native.toLowerCase().includes(q) ||
      l.code.toLowerCase().includes(q)
    );
  });

  const selectLanguage = useCallback(
    async (lang) => {
      const previousLang = i18n.language;
      trackEvent("language_selected", {
        language_code: lang.code,
        previous_language: previousLang,
      });
      setOpen(false);
      setSearch("");
      if (student) {
        // Show overlay FIRST, then apply all changes behind it
        setChangingLang(lang);
        setApiDone(false);
        // Small delay so overlay renders before UI shifts
        await new Promise((r) => setTimeout(r, 50));
        try {
          // Apply i18n + localStorage behind the overlay
          i18n.changeLanguage(lang.code);
          localStorage.setItem("ada_language", lang.code);
          const res = await updateLanguage(student.id, lang.code);
          const { translated_headings, session_cache_cleared } = res.data || {};
          if (translated_headings?.length > 0) {
            sessionDispatch({ type: "LANGUAGE_CHANGED", payload: { headings: translated_headings } });
          }
          if (session_cache_cleared && reloadCurrentChunk) {
            await reloadCurrentChunk();
          }
        } catch {
          // Still apply i18n even if API fails
          if (i18n.language !== lang.code) {
            i18n.changeLanguage(lang.code);
            localStorage.setItem("ada_language", lang.code);
          }
        } finally {
          // Let React finish re-rendering all state changes behind the overlay
          // before signaling completion (prevents visible loading flicker after overlay closes)
          await new Promise((r) => setTimeout(r, 600));
          setApiDone(true);
        }
      } else {
        // No student — just switch UI language instantly
        i18n.changeLanguage(lang.code);
        localStorage.setItem("ada_language", lang.code);
      }
    },
    [i18n, student, sessionDispatch, reloadCurrentChunk]
  );

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Focus search when opened
  useEffect(() => {
    if (open && searchRef.current) {
      searchRef.current.focus();
      setHighlightIdx(0);
    }
  }, [open]);

  // Keyboard navigation
  const handleKeyDown = (e) => {
    if (e.key === "Escape") {
      setOpen(false);
      setSearch("");
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlightIdx((prev) => Math.min(prev + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlightIdx((prev) => Math.max(prev - 1, 0));
    } else if (e.key === "Enter" && filtered[highlightIdx]) {
      selectLanguage(filtered[highlightIdx]);
    }
  };

  // Scroll highlighted item into view
  useEffect(() => {
    if (!listRef.current) return;
    const items = listRef.current.children;
    if (items[highlightIdx]) {
      items[highlightIdx].scrollIntoView({ block: "nearest" });
    }
  }, [highlightIdx]);

  return (
    <div ref={containerRef} style={{ position: "relative" }}>
      {prominent ? (
        /* ── Prominent trigger (Dashboard) ────────────────────────── */
        <button
          onClick={() => setOpen(!open)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "12px",
            padding: "10px 18px 10px 14px",
            background: "#FFFFFF",
            border: "2px solid #E2E8F0",
            borderRadius: "14px",
            cursor: "pointer",
            fontFamily: "'Outfit', sans-serif",
            transition: "all 0.2s ease",
            boxShadow: "0 2px 8px rgba(0,0,0,0.06)",
            minWidth: "180px",
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.borderColor = "#F97316";
            e.currentTarget.style.boxShadow = "0 4px 16px rgba(249,115,22,0.15)";
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.borderColor = "#E2E8F0";
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.06)";
          }}
          title={t("lang.search")}
        >
          {/* Flag */}
          <span style={{
            fontSize: "28px",
            lineHeight: 1,
            width: "36px",
            height: "36px",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            borderRadius: "10px",
            backgroundColor: "#FFF7ED",
            flexShrink: 0,
          }}>
            {currentLang.flag}
          </span>

          {/* Language names */}
          <div style={{ flex: 1, textAlign: "left", minWidth: 0 }}>
            <div style={{
              fontSize: "15px",
              fontWeight: 700,
              color: "#0F172A",
              lineHeight: 1.2,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}>
              {currentLang.native}
            </div>
            <div style={{
              fontSize: "11px",
              fontWeight: 500,
              color: "#94A3B8",
              lineHeight: 1.3,
              letterSpacing: "0.02em",
            }}>
              {currentLang.name}
            </div>
          </div>

          {/* Chevron */}
          <ChevronDown
            size={16}
            style={{
              color: "#94A3B8",
              flexShrink: 0,
              transition: "transform 0.2s",
              transform: open ? "rotate(180deg)" : "rotate(0deg)",
            }}
          />
        </button>
      ) : (
        /* ── Compact trigger (TopBar / other) ─────────────────────── */
        <button
          onClick={() => setOpen(!open)}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.3rem",
            padding: compact ? "0.3rem 0.6rem" : "0.4rem 0.8rem",
            background: "none",
            border: "1px solid var(--color-border)",
            borderRadius: "8px",
            color: "var(--color-text)",
            cursor: "pointer",
            fontFamily: "inherit",
            fontSize: compact ? "0.8rem" : "0.85rem",
            fontWeight: 600,
            transition: "all 0.2s",
          }}
          title={t("lang.search")}
        >
          <Globe size={compact ? 13 : 15} />
          <span>{currentLang.flag}</span>
          <span>{currentLang.code.toUpperCase()}</span>
        </button>
      )}

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            width: prominent ? "320px" : "280px",
            maxHeight: prominent ? "420px" : "360px",
            backgroundColor: "var(--color-surface, #FFFFFF)",
            border: "2px solid var(--color-border, #E2E8F0)",
            borderRadius: prominent ? "16px" : "12px",
            boxShadow: prominent
              ? "0 12px 40px rgba(0,0,0,0.12), 0 0 0 1px rgba(0,0,0,0.04)"
              : "0 8px 32px rgba(0,0,0,0.15)",
            zIndex: 1000,
            overflow: "hidden",
            display: "flex",
            flexDirection: "column",
          }}
          onKeyDown={handleKeyDown}
        >
          {/* Search input */}
          <div
            style={{
              padding: "0.6rem",
              borderBottom: "1px solid var(--color-border)",
            }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "0.4rem",
                padding: "0.5rem 0.7rem",
                borderRadius: "8px",
                border: "1.5px solid var(--color-border)",
                backgroundColor: "var(--color-bg)",
              }}
            >
              <Search size={14} color="var(--color-text-muted)" />
              <input
                ref={searchRef}
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value);
                  setHighlightIdx(0);
                }}
                placeholder={t("lang.search")}
                style={{
                  border: "none",
                  outline: "none",
                  background: "transparent",
                  color: "var(--color-text)",
                  fontSize: "0.85rem",
                  fontFamily: "inherit",
                  width: "100%",
                }}
              />
            </div>
          </div>

          {/* Language list */}
          <div
            ref={listRef}
            style={{
              overflowY: "auto",
              flex: 1,
              padding: "0.3rem",
            }}
          >
            {filtered.length === 0 && (
              <div
                style={{
                  padding: "1rem",
                  textAlign: "center",
                  color: "var(--color-text-muted)",
                  fontSize: "0.85rem",
                }}
              >
                {t("lang.noResults", "No languages found")}
              </div>
            )}
            {filtered.map((lang, idx) => {
              const isSelected = lang.code === i18n.language;
              const isHighlighted = idx === highlightIdx;
              return (
                <button
                  key={lang.code}
                  onClick={() => selectLanguage(lang)}
                  onMouseEnter={() => setHighlightIdx(idx)}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: prominent ? "12px" : "0.6rem",
                    width: "100%",
                    padding: prominent ? "10px 12px" : "0.55rem 0.7rem",
                    border: isSelected && prominent ? "1.5px solid #F97316" : "1.5px solid transparent",
                    borderRadius: prominent ? "12px" : "8px",
                    backgroundColor: isSelected && prominent
                      ? "#FFF7ED"
                      : isHighlighted
                        ? "var(--color-primary-light, #FFF7ED)"
                        : "transparent",
                    color: "var(--color-text, #0F172A)",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    fontSize: prominent ? "1rem" : "0.88rem",
                    textAlign: "left",
                    transition: "all 0.15s ease",
                  }}
                >
                  <span style={{
                    fontSize: prominent ? "1.5rem" : "1.2rem",
                    width: prominent ? "36px" : "24px",
                    textAlign: "center",
                    flexShrink: 0,
                  }}>
                    {lang.flag}
                  </span>
                  <span style={{ flex: 1, minWidth: 0 }}>
                    <span style={{ fontWeight: 700, fontSize: prominent ? "0.95rem" : undefined }}>{lang.native}</span>
                    <span
                      style={{
                        color: "var(--color-text-muted, #94A3B8)",
                        fontSize: prominent ? "0.78rem" : "0.8rem",
                        marginLeft: "0.4rem",
                        fontWeight: 400,
                      }}
                    >
                      {lang.name}
                    </span>
                  </span>
                  {isSelected && (
                    <Check size={prominent ? 20 : 16} color="#F97316" strokeWidth={3} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}

      <LanguageChangeOverlay
        open={!!changingLang}
        targetLanguage={changingLang}
        apiDone={apiDone}
        onComplete={() => setChangingLang(null)}
      />
    </div>
  );
}
