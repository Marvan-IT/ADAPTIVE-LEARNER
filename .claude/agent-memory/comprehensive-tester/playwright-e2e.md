---
name: playwright-e2e
description: Playwright E2E browser test suite for ADA frontend — config, helpers, patterns, and DOM facts
type: project
---

## File Locations

- `frontend/playwright.config.js` — Playwright config (baseURL: http://localhost:5173, timeout: 120s, retries: 1)
- `frontend/e2e/helpers.js` — Shared helpers (createStudent, navigateToLearn, waitForCards, MCQ helpers)
- `frontend/e2e/01-card-rendering.spec.js` — 6 tests: title, body content, KaTeX, images, dots, mobile
- `frontend/e2e/02-mcq-interaction.spec.js` — 5 tests: highlight, next-enable, feedback, replacement, mastery bar
- `frontend/e2e/03-struggling-student.spec.js` — 3 tests: recovery card, AssistantPanel, content after wrong
- `frontend/e2e/04-fast-student.spec.js` — 3 tests: content length, next-enable, difficulty stars
- `frontend/e2e/05-normal-student.spec.js` — 3 tests: prev disabled, bias buttons, prev nav
- `frontend/e2e/06-mode-switch.spec.js` — 2 tests: rapid advance stability, wrong-answers stability
- `frontend/e2e/07-section-weak.spec.js` — 3 tests: Socratic renders, type+send, score at end
- `frontend/e2e/08-complete-journey.spec.js` — 3 tests: welcome, map, full journey
- `frontend/e2e/09-features.spec.js` — 5 tests: customize panel, exit confirm, interest tags, Arabic, prereq modal

## Installation

```bash
cd frontend
npm install
npx playwright install chromium
npm run test:e2e
```

## Key DOM Facts (no data-testid attributes exist)

- Loading text: "ADA is crafting your lesson cards..." → i18n key `learning.craftingCards`
- Progress dots: `.rounded-full` divs (one per card)
- Card body: `.markdown-content` div
- MCQ options: `button:has(span:text-is("A"))` — pill buttons with circular letter badge
- Next button: `getByRole('button', { name: /^Next/ })`
- Finish button: `getByRole('button', { name: /Finish Cards|Check My Understanding/i })`
- Previous button: `getByRole('button', { name: /Previous/i })` — disabled at card 0
- AssistantPanel header: "ADA Helper" (i18n `assist.title`)
- Mastery bar: text "Mastery readiness"
- Difficulty stars: `span:text("★")` — only when card.difficulty != null
- Difficulty bias: buttons "Too Easy" / "Too Hard" — appear after currentCardIndex > 0
- Exit button: `getByRole('button', { name: /Exit Lesson/i })`
- Exit confirm text: "Exit lesson? Your progress will be lost."
- Prereq modal: text "Not quite ready yet!" with "Start anyway" button
- Customize panel: gear button `button:has-text("⚙")`, style `<select>`, interests `<input>`
- Socratic chat input: `<textarea>` or `input[placeholder*="answer"]`
- Interest tag: `span:has-text("football")` after pressing Enter in interest input

## Helper API Patterns

```js
// Create student and get ID
const studentId = await createStudent('Name', { preferred_language: 'ar' });

// Pre-seed session for API queries
const session = await createSession(studentId, CONCEPT_C1S1);

// Navigate (sets localStorage ada_student_id, then goes to /learn/{conceptId})
await navigateToLearn(page, studentId, CONCEPT_C1S1);

// Wait for cards (90s default)
await waitForCards(page);

// Answer MCQ correctly using API knowledge
await answerMCQCorrectly(page, session.id, cardIndex);
```

## Concept IDs

- `PREALG.C1.S1.INTRODUCTION_TO_WHOLE_NUMBERS`
- `PREALG.C1.S2.ADD_WHOLE_NUMBERS`
- `PREALG.C1.S3.SUBTRACT_WHOLE_NUMBERS`

## WRONG_FEEDBACK_MS

The app waits 1800ms after a wrong MCQ before showing replacement — always wait 2200ms+ in tests after a wrong click.

## Student isolation

Every test creates a unique student via `createStudent()` to prevent state pollution across tests.
