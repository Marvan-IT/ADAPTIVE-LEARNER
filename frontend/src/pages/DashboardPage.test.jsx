import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";

// ── Module mocks ─────────────────────────────────────────────────────────────
// Declared before the DashboardPage import so Vitest hoisting picks them up.

// Mock router — DashboardPage calls useNavigate but we don't navigate in tests.
vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

// Mock i18next — simple passthrough returning the fallback string.
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key, fallback) => (typeof fallback === "string" ? fallback : key),
    i18n: { language: "ml" },
  }),
}));

// Mock StudentContext — provide a minimal student with an id so useEffects fire.
vi.mock("../context/StudentContext", () => ({
  useStudent: () => ({
    student: {
      id: "student-ml-001",
      display_name: "Amal",
    },
    masteredConcepts: [],
    isHydrated: true,
  }),
}));

// Mock Zustand adaptive store — flatten selector calls to fixed values.
vi.mock("../store/adaptiveStore", () => ({
  useAdaptiveStore: (selector) =>
    selector({ xp: 0, level: 1, dailyStreak: 0 }),
}));

// Mock API calls — these are the two that fire from the first useEffect.
const mockGetSessions = vi.fn();
const mockGetStudentAnalytics = vi.fn();
vi.mock("../api/students", () => ({
  getSessions: (...args) => mockGetSessions(...args),
  getStudentAnalytics: (...args) => mockGetStudentAnalytics(...args),
}));

// Mock concepts API — fires from the second (subjects) useEffect.
vi.mock("../api/concepts", () => ({
  getAvailableBooks: vi.fn().mockResolvedValue({ data: [] }),
  getGraphFull: vi.fn().mockResolvedValue({ data: { nodes: [] } }),
}));

// Stub heavy UI dependencies that are not needed for this assertion.
vi.mock("../components/LanguageSelector", () => ({
  default: () => <div data-testid="language-selector" />,
}));

vi.mock("../components/ui", () => ({
  ProgressBar: () => <div />,
  Card: ({ children }) => <div>{children}</div>,
  Button: ({ children, onClick }) => <button onClick={onClick}>{children}</button>,
}));

vi.mock("framer-motion", () => ({
  motion: {
    div: ({ children, ...props }) => <div {...props}>{children}</div>,
  },
}));

// formatConceptTitle is the fallback — for this test it must NOT be called
// because concept_title is populated. Spy on it so we can optionally verify.
const mockFormatConceptTitle = vi.fn(() => "Formatted Fallback");
vi.mock("../utils/formatConceptTitle", () => ({
  formatConceptTitle: (...args) => mockFormatConceptTitle(...args),
}));

vi.mock("../theme/themes", () => ({
  staggerContainer: {},
  staggerItem: {},
}));

// Import AFTER all mocks are registered.
import DashboardPage from "./DashboardPage.jsx";

// ── Helpers ───────────────────────────────────────────────────────────────────

/**
 * A session object whose concept_title is set to the Malayalam string
 * "ഡാറ്റ ശേഖരണം" (Data Collection).  This is the non-English title that the
 * backend now returns via the LATERAL join translation (DLD §3.3 / §14.5).
 */
const ML_SESSION = {
  id: "sess-ml-001",
  concept_id: "business_statistics_1.1",
  concept_title: "ഡാറ്റ ശേഖരണം",
  book_slug: "business_statistics",
  book_title: "ബിസിനസ് സ്ഥിതിവിവരക്കണക്ക്",
  phase: "COMPLETED",
  check_score: 90,
  mastered: true,
  started_at: "2026-04-24T10:00:00Z",
  completed_at: "2026-04-24T10:30:00Z",
};

// ── Tests ─────────────────────────────────────────────────────────────────────

describe("DashboardPage — Recent Activity renders concept_title", () => {
  beforeEach(() => {
    vi.clearAllMocks();

    // Analytics — not the focus; just resolve to avoid console.error.
    mockGetStudentAnalytics.mockResolvedValue({ data: { total_study_time_sec: 0 } });
  });

  it("renders the Malayalam concept_title in the Recent Activity row", async () => {
    /**
     * Arrange: getSessions returns a completed session whose concept_title
     * is the Malayalam string "ഡാറ്റ ശേഖരണം".
     *
     * Act: render DashboardPage and wait for the async useEffect to resolve.
     *
     * Assert: the exact Malayalam string appears in the DOM (line 362 of
     * DashboardPage.jsx: `session.concept_title || formatConceptTitle(...)`).
     *
     * The fallback (formatConceptTitle) must NOT be called because
     * concept_title is non-empty — this confirms the wiring at §14.5 row 3.
     */
    mockGetSessions.mockResolvedValue({
      data: { sessions: [ML_SESSION] },
    });

    render(<DashboardPage />);

    // Wait for the async effect to settle and the session row to appear.
    const titleEl = await screen.findByText("ഡാറ്റ ശേഖരണം");
    expect(titleEl).toBeInTheDocument();

    // Confirm formatConceptTitle was NOT used as the primary render path.
    // It may be called for the subjects panel (second useEffect also calls
    // getSessions), so we only assert it was not invoked with our concept_id.
    expect(mockFormatConceptTitle).not.toHaveBeenCalledWith(
      "business_statistics_1.1",
      expect.anything()
    );
  });
});
