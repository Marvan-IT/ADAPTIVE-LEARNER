export const themes = {
  default: {
    name: "Default",
    emoji: "📚",
    greeting: "Welcome to your lesson!",
  },
  pirate: {
    name: "Pirate",
    emoji: "🏴‍☠️",
    greeting: "Ahoy, matey! Ready for adventure?",
  },
  astronaut: {
    name: "Astronaut",
    emoji: "🚀",
    greeting: "Mission control, we're ready for launch!",
  },
  gamer: {
    name: "Gamer",
    emoji: "🎮",
    greeting: "Player One, let's level up!",
  },
};

export const springs = {
  micro:  { type: "spring", stiffness: 500, damping: 30 },
  gentle: { type: "spring", stiffness: 200, damping: 20 },
  snappy: { type: "spring", stiffness: 400, damping: 25 },
  bouncy: { type: "spring", stiffness: 300, damping: 12 },
  slow:   { type: "spring", stiffness: 100, damping: 20 },
  burst:  { type: "spring", stiffness: 500, damping: 15 },
};

export const staggerContainer = {
  hidden: {},
  show: { transition: { staggerChildren: 0.06 } },
};

export const staggerItem = {
  hidden: { opacity: 0, y: 16 },
  show: { opacity: 1, y: 0, transition: { duration: 0.35, ease: [0.25, 0.1, 0.25, 1] } },
};
