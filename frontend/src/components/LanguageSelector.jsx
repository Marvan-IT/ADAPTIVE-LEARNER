import { useState, useRef, useEffect, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { LANGUAGES } from "../i18n";
import { useStudent } from "../context/StudentContext";
import { useSession } from "../context/SessionContext";
import { updateLanguage } from "../api/students";
import { Globe, Search, Check } from "lucide-react";
import { trackEvent } from "../utils/analytics";

export default function LanguageSelector({ compact = false }) {
  const { i18n, t } = useTranslation();
  const { student } = useStudent();
  const { dispatch: sessionDispatch } = useSession();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlightIdx, setHighlightIdx] = useState(0);
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
      i18n.changeLanguage(lang.code);
      localStorage.setItem("ada_language", lang.code);
      setOpen(false);
      setSearch("");
      if (student) {
        try {
          const res = await updateLanguage(student.id, lang.code);
          const { translated_headings } = res.data || {};
          if (translated_headings?.length > 0) {
            sessionDispatch({ type: "LANGUAGE_CHANGED", payload: { headings: translated_headings } });
          }
        } catch {
          // silent — localStorage is the primary persistence
        }
      }
    },
    [i18n, student, sessionDispatch]
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

      {open && (
        <div
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            right: 0,
            width: "280px",
            maxHeight: "360px",
            backgroundColor: "var(--color-surface)",
            border: "2px solid var(--color-border)",
            borderRadius: "12px",
            boxShadow: "0 8px 32px rgba(0,0,0,0.15)",
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
                No languages found
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
                    gap: "0.6rem",
                    width: "100%",
                    padding: "0.55rem 0.7rem",
                    border: "none",
                    borderRadius: "8px",
                    backgroundColor: isHighlighted
                      ? "var(--color-primary-light)"
                      : "transparent",
                    color: "var(--color-text)",
                    cursor: "pointer",
                    fontFamily: "inherit",
                    fontSize: "0.88rem",
                    textAlign: "left",
                    transition: "background-color 0.1s",
                  }}
                >
                  <span style={{ fontSize: "1.2rem", width: "24px", textAlign: "center" }}>
                    {lang.flag}
                  </span>
                  <span style={{ flex: 1 }}>
                    <span style={{ fontWeight: 600 }}>{lang.native}</span>
                    <span
                      style={{
                        color: "var(--color-text-muted)",
                        fontSize: "0.8rem",
                        marginLeft: "0.4rem",
                      }}
                    >
                      {lang.name}
                    </span>
                  </span>
                  {isSelected && (
                    <Check size={16} color="var(--color-primary)" strokeWidth={3} />
                  )}
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
