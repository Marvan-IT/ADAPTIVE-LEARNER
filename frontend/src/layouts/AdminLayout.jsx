import { Outlet, useLocation } from "react-router-dom";
import { AnimatePresence, motion } from "framer-motion";
import AdminSidebar from "../components/layout/AdminSidebar";
import AdminTopBar from "../components/layout/AdminTopBar";

export default function AdminLayout() {
  const location = useLocation();

  return (
    <div style={{ height: "100vh", display: "flex", overflow: "hidden", backgroundColor: "#FAFAFA" }}>
      <AdminSidebar />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <AdminTopBar />
        <main style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
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
