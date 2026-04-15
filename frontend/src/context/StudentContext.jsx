import { createContext, useContext, useState, useEffect, useCallback } from "react";
import i18n from "i18next";
import { getStudent, getStudentMastery } from "../api/students";
import { identifyStudent, resetUser, trackEvent } from "../utils/analytics";
import { useAdaptiveStore } from "../store/adaptiveStore";
import { useAuth } from "./AuthContext";

const StudentContext = createContext();

export function StudentProvider({ children }) {
  const { user, logout: authLogout } = useAuth();
  const [student, setStudentState] = useState(null);
  const [masteredConcepts, setMasteredConcepts] = useState([]);
  const [loading, setLoading] = useState(true);

  const initAdaptive = useAdaptiveStore((s) => s.init);

  // Load student data whenever auth user changes (or student_id changes)
  useEffect(() => {
    const studentId = user?.student_id;
    if (!studentId) {
      setStudentState(null);
      setMasteredConcepts([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    getStudent(studentId)
      .then((res) => {
        setStudentState(res.data);
        identifyStudent(res.data);
        trackEvent("existing_student_resumed", { student_id: res.data.id });
        // Sync i18n language from student profile
        if (res.data.preferred_language) {
          i18n.changeLanguage(res.data.preferred_language);
        }
        // Hydrate Zustand game store from DB values if present
        if (res.data.xp !== undefined || res.data.streak !== undefined) {
          initAdaptive({
            xp: res.data.xp ?? 0,
            streak: res.data.streak ?? 0,
            daily_streak: res.data.daily_streak ?? 0,
            daily_streak_best: res.data.daily_streak_best ?? 0,
          });
        }
        return getStudentMastery(studentId);
      })
      .then((res) => {
        setMasteredConcepts(res.data.mastered_concepts || []);
      })
      .catch((err) => {
        console.error("[StudentContext] Failed to load student:", err);
      })
      .finally(() => setLoading(false));
  }, [user?.student_id, initAdaptive]);

  // setStudent kept for compatibility — updates local state only
  const setStudent = useCallback((studentData) => {
    setStudentState(studentData);
  }, []);

  // Full profile + mastery refresh — catches admin changes (name, language, mastery grants)
  const refreshStudent = useCallback(async () => {
    if (!user?.student_id) return;
    try {
      const res = await getStudent(user.student_id);
      setStudentState(res.data);
      if (res.data.preferred_language) {
        i18n.changeLanguage(res.data.preferred_language);
      }
      if (res.data.xp !== undefined || res.data.streak !== undefined) {
        initAdaptive({
          xp: res.data.xp ?? 0,
          streak: res.data.streak ?? 0,
          daily_streak: res.data.daily_streak ?? 0,
          daily_streak_best: res.data.daily_streak_best ?? 0,
        });
      }
      const masteryRes = await getStudentMastery(user.student_id);
      setMasteredConcepts(masteryRes.data.mastered_concepts || []);
    } catch (err) {
      console.error("[StudentContext] refreshStudent failed:", err);
    }
  }, [user?.student_id, initAdaptive]);

  // Auto-refresh when tab regains focus (catches admin changes made while student was away)
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === "visible" && user?.student_id) {
        refreshStudent();
      }
    };
    document.addEventListener("visibilitychange", handleVisibility);
    return () => document.removeEventListener("visibilitychange", handleVisibility);
  }, [refreshStudent, user?.student_id]);

  const refreshMastery = useCallback(async () => {
    if (!student) return;
    try {
      const res = await getStudentMastery(student.id);
      setMasteredConcepts(res.data.mastered_concepts || []);
    } catch (err) {
      console.error("Failed to refresh mastery:", err);
    }
  }, [student]);

  // selectStudent kept for legacy compatibility (e.g. after profile update)
  const selectStudent = useCallback(
    async (studentData) => {
      setStudentState(studentData);
      identifyStudent(studentData);
      if (studentData.preferred_language) {
        i18n.changeLanguage(studentData.preferred_language);
      }
      if (studentData.xp !== undefined || studentData.streak !== undefined) {
        initAdaptive({
          xp: studentData.xp ?? 0,
          streak: studentData.streak ?? 0,
          daily_streak: studentData.daily_streak ?? 0,
          daily_streak_best: studentData.daily_streak_best ?? 0,
        });
      }
      try {
        const res = await getStudentMastery(studentData.id);
        setMasteredConcepts(res.data.mastered_concepts || []);
      } catch {
        setMasteredConcepts([]);
      }
    },
    [initAdaptive]
  );

  const logout = useCallback(async () => {
    trackEvent("student_logout", { student_id: student?.id });
    setStudentState(null);
    setMasteredConcepts([]);
    resetUser();
    // Delegate token/session cleanup to AuthContext
    await authLogout();
  }, [student?.id, authLogout]);

  return (
    <StudentContext.Provider
      value={{
        student,
        setStudent,
        selectStudent,
        masteredConcepts,
        refreshMastery,
        refreshStudent,
        logout,
        loading,
      }}
    >
      {children}
    </StudentContext.Provider>
  );
}

export function useStudent() {
  const context = useContext(StudentContext);
  if (!context) throw new Error("useStudent must be used within StudentProvider");
  return context;
}
