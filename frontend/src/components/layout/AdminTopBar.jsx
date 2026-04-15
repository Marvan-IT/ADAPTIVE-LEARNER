import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";
import { Breadcrumb } from "../ui";

function getBreadcrumbs(pathname, t) {
  const base = { label: t("admin.nav.adminBadge", "Admin"), href: "/admin" };
  if (pathname === "/admin") return [base, { label: t("admin.nav.dashboard", "Dashboard") }];
  if (pathname === "/admin/students") return [base, { label: t("admin.nav.students", "Students") }];
  if (pathname.match(/^\/admin\/students\/.+\/progress/)) return [base, { label: t("admin.nav.students", "Students"), href: "/admin/students" }, { label: t("admin.breadcrumb.progress", "Progress") }];
  if (pathname.match(/^\/admin\/students\/.+/)) return [base, { label: t("admin.nav.students", "Students"), href: "/admin/students" }, { label: t("admin.breadcrumb.detail", "Detail") }];
  if (pathname === "/admin/sessions") return [base, { label: t("admin.nav.sessions", "Sessions") }];
  if (pathname === "/admin/analytics") return [base, { label: t("admin.nav.analytics", "Analytics") }];
  if (pathname === "/admin/settings") return [base, { label: t("admin.nav.settings", "Settings") }];
  if (pathname.match(/^\/admin\/subjects\//)) return [base, { label: t("admin.nav.subjects", "Subjects") }];
  if (pathname.match(/^\/admin\/books\/.+\/track/)) return [base, { label: t("admin.breadcrumb.books", "Books") }, { label: t("admin.breadcrumb.pipeline", "Pipeline") }];
  if (pathname.match(/^\/admin\/books\/.+\/review/)) return [base, { label: t("admin.breadcrumb.books", "Books") }, { label: t("admin.breadcrumb.review", "Review") }];
  if (pathname.match(/^\/admin\/books\/.+\/content/)) return [base, { label: t("admin.breadcrumb.books", "Books") }, { label: t("admin.breadcrumb.content", "Content") }];
  if (pathname === "/admin/users") return [base, { label: t("admin.nav.users", "Users") }];
  return [base];
}

/* Sequential back button: each admin page goes to its logical parent */
function getBackTarget(pathname, t) {
  // Dashboard — no back button
  if (pathname === "/admin") return null;

  // Student detail → Students list
  if (pathname.match(/^\/admin\/students\/.+\/progress$/)) {
    const id = pathname.split("/")[3];
    return { label: t("admin.nav.backToStudent", "Back to Student"), path: `/admin/students/${id}` };
  }
  if (pathname.match(/^\/admin\/students\/.+/)) {
    return { label: t("admin.nav.backToStudents", "Back to Students"), path: "/admin/students" };
  }

  // Book sub-pages → Dashboard (books are accessed from admin dashboard subject cards)
  if (pathname.match(/^\/admin\/books\/.+\/(track|review|content)$/)) {
    return { label: t("admin.nav.backToDashboard", "Back to Dashboard"), path: "/admin" };
  }

  // Subject page → Dashboard
  if (pathname.match(/^\/admin\/subjects\//)) {
    return { label: t("admin.nav.backToDashboard", "Back to Dashboard"), path: "/admin" };
  }

  // All other top-level admin pages → Dashboard
  return { label: t("admin.nav.backToDashboard", "Back to Dashboard"), path: "/admin" };
}

export default function AdminTopBar() {
  const location = useLocation();
  const navigate = useNavigate();
  const { t } = useTranslation();

  const isAdminHome = location.pathname === "/admin";
  const back = getBackTarget(location.pathname, t);

  return (
    <header style={{
      height: "60px", flexShrink: 0, display: "flex", alignItems: "center",
      justifyContent: "space-between", padding: "0 24px",
      backgroundColor: "#FFFFFF", borderBottom: "1px solid #E2E8F0",
    }}>
      {/* Left: Back button or Breadcrumb on admin home */}
      {isAdminHome ? (
        <Breadcrumb items={getBreadcrumbs(location.pathname, t)} />
      ) : (
        <div style={{ display: "flex", alignItems: "center", gap: "16px" }}>
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
          <div style={{ width: "1px", height: "20px", background: "#E2E8F0" }} />
          <Breadcrumb items={getBreadcrumbs(location.pathname, t)} />
        </div>
      )}
    </header>
  );
}
