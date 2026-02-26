import { createContext, useContext, useState, useEffect, useCallback } from "react";
import i18n from "i18next";
import { getStudent, getStudentMastery } from "../api/students";
import { identifyStudent, resetUser, trackEvent } from "../utils/analytics";

const StudentContext = createContext();

export function StudentProvider({ children }) {
  const [student, setStudentState] = useState(null);
  const [masteredConcepts, setMasteredConcepts] = useState([]);
  const [loading, setLoading] = useState(true);

  // Rehydrate from localStorage on mount
  useEffect(() => {
    const savedId = localStorage.getItem("ada_student_id");
    if (savedId) {
      getStudent(savedId)
        .then((res) => {
          setStudentState(res.data);
          identifyStudent(res.data);
          trackEvent("existing_student_resumed", { student_id: res.data.id });
          // Sync i18n language from student profile
          if (res.data.preferred_language) {
            i18n.changeLanguage(res.data.preferred_language);
          }
          return getStudentMastery(savedId);
        })
        .then((res) => {
          setMasteredConcepts(res.data.mastered_concepts || []);
        })
        .catch(() => {
          localStorage.removeItem("ada_student_id");
        })
        .finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
  }, []);

  const setStudent = (studentData) => {
    setStudentState(studentData);
    if (studentData) {
      localStorage.setItem("ada_student_id", studentData.id);
    } else {
      localStorage.removeItem("ada_student_id");
    }
  };

  const refreshMastery = useCallback(async () => {
    if (!student) return;
    try {
      const res = await getStudentMastery(student.id);
      setMasteredConcepts(res.data.mastered_concepts || []);
    } catch (err) {
      console.error("Failed to refresh mastery:", err);
    }
  }, [student]);

  const selectStudent = useCallback(async (studentData) => {
    setStudentState(studentData);
    localStorage.setItem("ada_student_id", studentData.id);
    identifyStudent(studentData);
    // Sync i18n language from student profile
    if (studentData.preferred_language) {
      i18n.changeLanguage(studentData.preferred_language);
    }
    try {
      const res = await getStudentMastery(studentData.id);
      setMasteredConcepts(res.data.mastered_concepts || []);
    } catch {
      setMasteredConcepts([]);
    }
  }, []);

  const logout = () => {
    trackEvent("student_logout", { student_id: student?.id });
    setStudentState(null);
    setMasteredConcepts([]);
    localStorage.removeItem("ada_student_id");
    resetUser();
  };

  return (
    <StudentContext.Provider
      value={{ student, setStudent, selectStudent, masteredConcepts, refreshMastery, logout, loading }}
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
