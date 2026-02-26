import { createContext, useContext, useState, useEffect } from "react";

const ThemeContext = createContext();

export function ThemeProvider({ children }) {
  const [style, setStyleState] = useState(() => {
    return localStorage.getItem("ada_style") || "default";
  });

  useEffect(() => {
    document.documentElement.setAttribute("data-theme", style === "default" ? "" : style);
    localStorage.setItem("ada_style", style);
  }, [style]);

  const setStyle = (newStyle) => {
    setStyleState(newStyle);
  };

  return (
    <ThemeContext.Provider value={{ style, setStyle }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
