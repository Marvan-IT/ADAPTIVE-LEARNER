import { createContext, useContext, useState, useLayoutEffect } from "react";

const ThemeContext = createContext();

export function ThemeProvider({ children }) {
  // UI theme: dark | light — never sent to backend
  const [theme, setThemeState] = useState(() => {
    const saved = localStorage.getItem("ada_theme");
    if (saved === "light" || saved === "dark") return saved;
    // Migrate old ada_style "dark"/"light" values
    const oldStyle = localStorage.getItem("ada_style");
    if (oldStyle === "dark" || oldStyle === "light") return oldStyle;
    return "light";
  });

  // Teaching style: default | pirate | astronaut | gamer — sent to backend
  const [teachingStyle, setTeachingStyleState] = useState(() => {
    const saved = localStorage.getItem("ada_teaching_style");
    if (saved && /^(default|pirate|astronaut|gamer)$/.test(saved)) return saved;
    // Migrate old ada_style if it was a valid teaching style
    const oldStyle = localStorage.getItem("ada_style");
    if (oldStyle && /^(default|pirate|astronaut|gamer)$/.test(oldStyle)) return oldStyle;
    return "default";
  });

  // data-theme drives all CSS: use teaching style when it has its own theme, else use dark/light
  useLayoutEffect(() => {
    const dataTheme = (teachingStyle !== "default") ? teachingStyle : theme;
    document.documentElement.setAttribute("data-theme", dataTheme);
    localStorage.setItem("ada_theme", theme);
    localStorage.setItem("ada_teaching_style", teachingStyle);
  }, [theme, teachingStyle]);

  const toggleTheme = () => {
    setThemeState((prev) => (prev === "dark" ? "light" : "dark"));
  };

  const setStyle = (newStyle) => {
    if (/^(default|pirate|astronaut|gamer)$/.test(newStyle)) {
      setTeachingStyleState(newStyle);
    } else if (newStyle === "dark" || newStyle === "light") {
      // Backwards compat: if someone passes a theme value, treat as theme toggle
      setThemeState(newStyle);
    }
  };

  const isDark = theme === "dark" || theme === "astronaut" || theme === "gamer";

  return (
    <ThemeContext.Provider value={{
      style: teachingStyle,    // backward compat — SessionContext reads this
      teachingStyle,
      theme,
      setStyle,
      setTeachingStyle: setTeachingStyleState,
      toggleTheme,
      isDark,
    }}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const context = useContext(ThemeContext);
  if (!context) throw new Error("useTheme must be used within ThemeProvider");
  return context;
}
