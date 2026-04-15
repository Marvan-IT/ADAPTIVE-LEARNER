import { useState, useEffect } from "react";
import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import StudentSidebar from "../components/layout/StudentSidebar";
import StudentTopBar from "../components/layout/StudentTopBar";

export default function StudentLayout() {
  const location = useLocation();
  const [collapsed, setCollapsed] = useState(() => {
    try {
      return localStorage.getItem("ada_sidebar_collapsed") === "true";
    } catch {
      return false;
    }
  });

  // Persist collapse state
  useEffect(() => {
    try {
      localStorage.setItem("ada_sidebar_collapsed", String(collapsed));
    } catch {}
  }, [collapsed]);

  // Auto-collapse on /learn/*, auto-expand on other routes
  useEffect(() => {
    if (location.pathname.startsWith("/learn/")) {
      setCollapsed(true);
    } else {
      setCollapsed(false);
    }
  }, [location.pathname]);

  return (
    <div style={{ height: "100vh", display: "flex", overflow: "hidden", backgroundColor: "#FAFAFA" }}>
      <StudentSidebar
        collapsed={collapsed}
        onToggleCollapse={() => setCollapsed((v) => !v)}
      />

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <StudentTopBar />

        <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "auto" }}>
          <AnimatePresence mode="wait">
            <motion.div
              key={location.pathname}
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -4 }}
              transition={{ duration: 0.18, ease: "easeOut" }}
              style={{ minHeight: "100%" }}
            >
              <Outlet />
            </motion.div>
          </AnimatePresence>
        </main>
      </div>
    </div>
  );
}
