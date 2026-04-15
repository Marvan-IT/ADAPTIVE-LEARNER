import { Navigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useAuth } from "../context/AuthContext";

export default function ProtectedRoute({ allowedRoles, children }) {
  const { user, loading, isAuthenticated } = useAuth();
  const location = useLocation();
  const { t } = useTranslation();

  if (loading) {
    return (
      <div
        style={{
          display: "flex",
          justifyContent: "center",
          alignItems: "center",
          height: "100vh",
          background: "#0f0a1a",
        }}
      >
        <div style={{ textAlign: "center" }}>
          <div
            style={{
              width: "44px",
              height: "44px",
              margin: "0 auto 1rem",
              borderRadius: "50%",
              border: "3px solid var(--color-primary)",
              borderTopColor: "transparent",
              animation: "spin 0.8s linear infinite",
            }}
            aria-hidden="true"
          />
          <p style={{ color: "var(--color-text-muted)", fontSize: "1rem" }}>{t("common.loading", "Loading...")}</p>
        </div>
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    return <Navigate to={user.role === "admin" ? "/admin" : "/map"} replace />;
  }

  return children;
}
