import { useEffect } from "react";
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom";
import { ThemeProvider } from "./context/ThemeContext";
import { StudentProvider } from "./context/StudentContext";
import { SessionProvider } from "./context/SessionContext";
import WelcomePage from "./pages/WelcomePage";
import ConceptMapPage from "./pages/ConceptMapPage";
import LearningPage from "./pages/LearningPage";
import AppShell from "./components/layout/AppShell";
import { trackPageView } from "./utils/analytics";

function PageViewTracker() {
  const location = useLocation();
  useEffect(() => {
    trackPageView(location.pathname);
  }, [location]);
  return null;
}

export default function App() {
  return (
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
              </Route>
              <Route path="*" element={<Navigate to="/" />} />
            </Routes>
          </SessionProvider>
        </StudentProvider>
      </ThemeProvider>
    </BrowserRouter>
  );
}
