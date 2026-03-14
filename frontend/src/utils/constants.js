export const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? "";
export const MASTERY_THRESHOLD = 70;

export const STYLES = [
  { id: "default", label: "Default", icon: "BookOpen", description: "Friendly tutor" },
  { id: "pirate", label: "Pirate", icon: "Skull", description: "Captain Calc" },
  { id: "astronaut", label: "Astronaut", icon: "Rocket", description: "Commander Count" },
  { id: "gamer", label: "Gamer", icon: "Gamepad2", description: "Player One" },
];

export const SUGGESTED_INTERESTS = [
  "video games", "sports", "animals", "space", "cooking", "music",
  "minecraft", "dinosaurs", "art", "robots",
];
