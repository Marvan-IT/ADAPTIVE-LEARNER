import { useEffect, Component } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, Outlet } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider } from "./context/AuthContext";
import { StudentProvider } from "./context/StudentContext";
import { SessionProvider } from "./context/SessionContext";
import { useAuth } from "./context/AuthContext";
import ProtectedRoute from "./components/ProtectedRoute";
import LoginPage from "./pages/LoginPage";
import RegisterPage from "./pages/RegisterPage";
import OtpVerifyPage from "./pages/OtpVerifyPage";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import ConceptMapPage from "./pages/ConceptMapPage";
import LearningPage from "./pages/LearningPage";
import StudentHistoryPage from "./pages/StudentHistoryPage";
import AdminPage from "./pages/AdminPage";
import AdminSubjectPage from "./pages/AdminSubjectPage";
import AdminTrackPage from "./pages/AdminTrackPage";
import AdminReviewPage from "./pages/AdminReviewPage";
import AppShell from "./components/layout/AppShell";
import { trackPageView } from "./utils/analytics";

class ErrorBoundary extends Component {
  constructor(props) { super(props); this.state = { error: null }; }
  static getDerivedStateFromError(error) { return { error }; }
  render() {
    if (this.state.error) {
      return (
        <div style={{ padding: "2rem", fontFamily: "monospace", color: "var(--color-danger)", background: "var(--color-bg)" }}>
          <h2>Something crashed</h2>
          <pre style={{ whiteSpace: "pre-wrap", fontSize: "0.8rem" }}>{String(this.state.error)}</pre>
          <button onClick={() => { this.setState({ error: null }); window.location.href = "/"; }}
            style={{ marginTop: "1rem", padding: "0.5rem 1rem", cursor: "pointer" }}>
            Go back home
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

function PageViewTracker() {
  const location = useLocation();
  useEffect(() => {
    trackPageView(location.pathname);
  }, [location]);
  return null;
}

function RootRedirect() {
  const { user, loading } = useAuth();
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
        <div
          style={{
            width: "44px",
            height: "44px",
            borderRadius: "50%",
            border: "3px solid #7c3aed",
            borderTopColor: "transparent",
            animation: "spin 0.8s linear infinite",
          }}
          aria-hidden="true"
        />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "admin" ? "/admin" : "/map"} replace />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <PageViewTracker />
        <ThemeProvider>
          <AuthProvider>
            <StudentProvider>
              <SessionProvider>
                <Routes>
                  {/* Public auth routes */}
                  <Route path="/login" element={<LoginPage />} />
                  <Route path="/register" element={<RegisterPage />} />
                  <Route path="/verify-otp" element={<OtpVerifyPage />} />
                  <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                  <Route path="/reset-password" element={<ResetPasswordPage />} />

                  {/* Student routes (protected) */}
                  <Route
                    element={
                      <ProtectedRoute allowedRoles={["student"]}>
                        <AppShell />
                      </ProtectedRoute>
                    }
                  >
                    <Route path="/map" element={<ConceptMapPage />} />
                    <Route path="/learn/:conceptId" element={<LearningPage />} />
                    <Route path="/history" element={<StudentHistoryPage />} />
                  </Route>

                  {/* Admin routes (protected) */}
                  <Route
                    element={
                      <ProtectedRoute allowedRoles={["admin"]}>
                        <Outlet />
                      </ProtectedRoute>
                    }
                  >
                    <Route path="/admin" element={<AdminPage />} />
                    <Route path="/admin/subjects/:subjectSlug" element={<AdminSubjectPage />} />
                    <Route path="/admin/books/:slug/track" element={<AdminTrackPage />} />
                    <Route path="/admin/books/:slug/review" element={<AdminReviewPage />} />
                  </Route>

                  {/* Root redirect */}
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="*" element={<Navigate to="/login" replace />} />
                </Routes>
              </SessionProvider>
            </StudentProvider>
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
