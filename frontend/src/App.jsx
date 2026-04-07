import { useEffect, Component } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { StudentProvider } from "./context/StudentContext";
import { SessionProvider } from "./context/SessionContext";
import WelcomePage from "./pages/WelcomePage";
import ConceptMapPage from "./pages/ConceptMapPage";
import LearningPage from "./pages/LearningPage";
import StudentHistoryPage from "./pages/StudentHistoryPage";
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

export default function App() {
  return (
    <ErrorBoundary>
    <BrowserRouter>
      <PageViewTracker />
      <ThemeProvider>
        <StudentProvider>
          <SessionProvider>
            <Routes>
              <Route path="/" element={<WelcomePage />} />
              <Route element={<AppShell />}>
                <Route path="/map" element={<ConceptMapPage />} />
                <Route path="/learn/:conceptId" element={<LearningPage />} />
                <Route path="/history" element={<StudentHistoryPage />} />
              </Route>
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </SessionProvider>
        </StudentProvider>
      </ThemeProvider>
    </BrowserRouter>
    </ErrorBoundary>
  );
}
