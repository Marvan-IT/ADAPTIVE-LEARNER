import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";
import { Breadcrumb } from "../ui";

function getBreadcrumbs(pathname, t) {
  const base = { label: t("app.title", "Adaptive Learner"), href: "/map" };
  if (pathname.startsWith("/learn/")) return [base, { label: t("nav.learning") }];
  if (pathname === "/map") return [base, { label: t("nav.conceptMap") }];
  if (pathname === "/dashboard") return [base, { label: t("nav.dashboard", "Dashboard") }];
  if (pathname === "/history") return [base, { label: t("nav.history", "History") }];
  if (pathname === "/leaderboard") return [base, { label: t("nav.leaderboard", "Leaderboard") }];
  if (pathname === "/achievements") return [base, { label: t("nav.achievements", "Achievements") }];
  if (pathname === "/settings") return [base, { label: t("nav.settings") }];
  return [base];
}

export default function StudentTopBar() {
  const { t } = useTranslation();
  const location = useLocation();
  const navigate = useNavigate();
  const isDashboard = location.pathname === "/dashboard";

  const isMap = location.pathname === "/map";

  /* Sequential back button: each page goes to its logical parent.
     /map has its own in-page back button + breadcrumb, so skip here. */
  const getBackTarget = () => {
    const p = location.pathname;
    if (p.startsWith("/learn/")) {
      const params = new URLSearchParams(location.search);
      const bookSlug = params.get("book_slug");
      return {
        label: t("nav.back", "Back"),
        path: bookSlug ? `/map?book=${encodeURIComponent(bookSlug)}` : "/map",
      };
    }
    return { label: t("nav.backToDashboard", "Back to Dashboard"), path: "/dashboard" };
  };

  const back = (isDashboard || isMap) ? null : getBackTarget();

  return (
    <header style={{
      height: "56px", flexShrink: 0, display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 24px",
      background: "#fff", borderBottom: "1px solid #e2e8f0",
    }}>
      {/* Left: Back button, or breadcrumb on dashboard.
           /map has its own in-page breadcrumb so we show nothing here. */}
      {back ? (
        <button
          onClick={() => navigate(back.path)}
          style={{
            display: "flex", alignItems: "center", gap: "6px",
            background: "none", border: "none", cursor: "pointer",
            color: "#64748b", fontSize: "13px", fontWeight: 500,
            padding: "6px 10px", borderRadius: "8px",
            transition: "background-color 0.15s",
          }}
          className="hover:bg-slate-50"
        >
          <ArrowLeft size={16} />
          {back.label}
        </button>
      ) : isDashboard ? (
        <Breadcrumb items={getBreadcrumbs(location.pathname, t)} />
      ) : null}

    </header>
  );
}
