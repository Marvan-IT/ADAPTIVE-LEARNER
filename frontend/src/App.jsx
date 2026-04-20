import { useEffect, Component } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation, Outlet } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { AuthProvider } from "./context/AuthContext";
import { StudentProvider } from "./context/StudentContext";
import { SessionProvider } from "./context/SessionContext";
import { ToastProvider, Toaster } from "./components/ui/Toast";
import { DialogProvider } from "./context/DialogProvider";
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
import AdminAnalyticsPage from "./pages/AdminAnalyticsPage";
import AdminSettingsPage from "./pages/AdminSettingsPage";
import AdminSupportPage from "./pages/AdminSupportPage";
import AdminStudentsPage from "./pages/AdminStudentsPage";
import AdminStudentDetailPage from "./pages/AdminStudentDetailPage";
import AdminSessionsPage from "./pages/AdminSessionsPage";
import AdminBookContentPage from "./pages/AdminBookContentPage";
import LeaderboardPage from "./pages/LeaderboardPage";
import AdminStudentProgressReport from "./pages/AdminStudentProgressReport";
import BadgeCelebration from "./components/game/BadgeCelebration";
import AppShell from "./components/layout/AppShell";
import StudentLayout from "./layouts/StudentLayout";
import AdminLayout from "./layouts/AdminLayout";
import AuthLayout from "./layouts/AuthLayout";
import DashboardPage from "./pages/DashboardPage";
import AchievementsPage from "./pages/AchievementsPage";
import SettingsPage from "./pages/SettingsPage";
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

function NotFoundRedirect() {
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
            border: "3px solid var(--color-primary)",
            borderTopColor: "transparent",
            animation: "spin 0.8s linear infinite",
          }}
          aria-hidden="true"
        />
      </div>
    );
  }
  if (user) return <Navigate to="/map" replace />;
  return <Navigate to="/" replace />;
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
            border: "3px solid var(--color-primary)",
            borderTopColor: "transparent",
            animation: "spin 0.8s linear infinite",
          }}
          aria-hidden="true"
        />
      </div>
    );
  }
  if (!user) return <Navigate to="/login" replace />;
  return <Navigate to={user.role === "admin" ? "/admin" : "/dashboard"} replace />;
}

export default function App() {
  return (
    <ErrorBoundary>
      <BrowserRouter>
        <PageViewTracker />
        <ThemeProvider>
          <AuthProvider>
            <ToastProvider>
              <DialogProvider>
                <StudentProvider>
                  <SessionProvider>
                    <Routes>
                  {/* Public auth routes (shared layout) */}
                  <Route element={<AuthLayout />}>
                    <Route path="/login" element={<LoginPage />} />
                    <Route path="/register" element={<RegisterPage />} />
                    <Route path="/verify-otp" element={<OtpVerifyPage />} />
                    <Route path="/forgot-password" element={<ForgotPasswordPage />} />
                    <Route path="/reset-password" element={<ResetPasswordPage />} />
                  </Route>

                  {/* Student routes (protected) */}
                  <Route
                    element={
                      <ProtectedRoute allowedRoles={["student"]}>
                        <StudentLayout />
                      </ProtectedRoute>
                    }
                  >
                    <Route path="/dashboard" element={<DashboardPage />} />
                    <Route path="/map" element={<ConceptMapPage />} />
                    <Route path="/learn/:conceptId" element={<LearningPage />} />
                    <Route path="/history" element={<StudentHistoryPage />} />
                    <Route path="/leaderboard" element={<LeaderboardPage />} />
                    <Route path="/achievements" element={<AchievementsPage />} />
                    <Route path="/settings" element={<SettingsPage />} />
                  </Route>

                  {/* Admin routes (protected) */}
                  <Route
                    element={
                      <ProtectedRoute allowedRoles={["admin"]}>
                        <AdminLayout />
                      </ProtectedRoute>
                    }
                  >
                    <Route path="/admin" element={<AdminPage />} />
                    <Route path="/admin/subjects/:subjectSlug" element={<AdminSubjectPage />} />
                    <Route path="/admin/books/:slug/track" element={<AdminTrackPage />} />
                    <Route path="/admin/books/:slug/review" element={<AdminReviewPage />} />
                    <Route path="/admin/books/:slug/content" element={<AdminBookContentPage />} />
                    <Route path="/admin/analytics" element={<AdminAnalyticsPage />} />
                    <Route path="/admin/support" element={<AdminSupportPage />} />
                    <Route path="/admin/settings" element={<AdminSettingsPage />} />
                    <Route path="/admin/students" element={<AdminStudentsPage />} />
                    <Route path="/admin/students/:id" element={<AdminStudentDetailPage />} />
                    <Route path="/admin/students/:id/progress" element={<AdminStudentProgressReport />} />
                    <Route path="/admin/sessions" element={<AdminSessionsPage />} />
                  </Route>

                  {/* Root redirect */}
                  <Route path="/" element={<RootRedirect />} />
                  <Route path="*" element={<NotFoundRedirect />} />
                </Routes>
                    <BadgeCelebration />
                  </SessionProvider>
                </StudentProvider>
                <Toaster />
              </DialogProvider>
            </ToastProvider>
          </AuthProvider>
        </ThemeProvider>
      </BrowserRouter>
    </ErrorBoundary>
  );
}
