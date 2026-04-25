# DLD — UX Fixes: Dashboard & Settings

**Slug:** `ux-fixes-dashboard-settings`
**Date:** 2026-04-23

---

## 1. Component Breakdown

| Component | File | Responsibility in this changeset |
|-----------|------|----------------------------------|
| StudentContext | `frontend/src/context/StudentContext.jsx` | Expose `isHydrated: boolean`; reset it on user change |
| StudentSidebar | `frontend/src/components/layout/StudentSidebar.jsx` | Render skeleton when `!isHydrated` |
| DashboardPage | `frontend/src/pages/DashboardPage.jsx` | Render skeleton stat card for XP when `!isHydrated` |
| AppShell | `frontend/src/components/layout/AppShell.jsx` | Wrap logout in `useDialog().confirm()` |
| SettingsPage | `frontend/src/pages/SettingsPage.jsx` | Add autofill-suppression attrs to custom-interest input |
| teaching_router | `backend/src/api/teaching_router.py` | Add `"age"` key to GET dict |
| Locale files | `frontend/src/locales/*.json` (13 files) | Verify `confirm.logoutTitle`, `confirm.logoutMessage`, `confirm.cancel` (nested) present in all 13 |

---

## 2. Fix 1 — XP/Level Flicker: `StudentContext.jsx`

### 2.1 New interface

```
StudentContext value (after fix):
{
  student,          // StudentResponse | null
  isHydrated,       // boolean — NEW. true only after initAdaptive() has been called
  setStudent,
  selectStudent,
  masteredConcepts,
  refreshMastery,
  refreshStudent,
  logout,
  loading,          // unchanged — covers getStudent + getStudentMastery
}
```

### 2.2 State additions

Add one piece of state at the top of `StudentProvider` (alongside `loading`):

```
const [isHydrated, setIsHydrated] = useState(false);
```

### 2.3 Hydration effect — change description

**File:** `frontend/src/context/StudentContext.jsx`, lines 19–56.

The existing `useEffect` depends on `[user?.student_id, initAdaptive]`. Apply these three edits inside it:

1. **Early-return branch (no studentId, lines ~22–25):** After `setStudentState(null)` and before `setLoading(false)`, add `setIsHydrated(false)`. This handles logout and user-switch cases.

2. **Inside the `.then()` that calls `initAdaptive()` (lines ~39–46):** After the `initAdaptive({ ... })` call, add `setIsHydrated(true)`. This is the exact moment Zustand xp/level/streak are populated from real DB values.

3. **`.catch()` handler (line ~52–54):** No change — `isHydrated` remains `false` on error, which is the correct safe default (skeleton stays visible rather than flashing wrong values).

State transition:
```
mount with user.student_id
  → isHydrated = false (initial)
  → setLoading(true)
  → getStudent() resolves
  → initAdaptive(...)
  → isHydrated = true          ← skeleton gate opens
  → getStudentMastery() resolves
  → setLoading(false)

mount without user.student_id (logout / user change)
  → isHydrated = false         ← reset (explicit set, not relying on useState init)
  → setLoading(false)
```

`refreshStudent()` (lines 64–85) also calls `initAdaptive()`. Add `setIsHydrated(true)` immediately after `initAdaptive(...)` inside `refreshStudent` as well — handles tab-focus re-hydration path.

`selectStudent()` (lines 109–132) also calls `initAdaptive()`. Same: add `setIsHydrated(true)` after the call.

### 2.4 Context.Provider value

Add `isHydrated` to the value object at line 145:

```jsx
<StudentContext.Provider
  value={{
    student,
    isHydrated,       // NEW
    setStudent,
    selectStudent,
    masteredConcepts,
    refreshMastery,
    refreshStudent,
    logout,
    loading,
  }}
>
```

---

## 3. Fix 1 (cont.) — Skeleton rendering: `StudentSidebar.jsx`

**File:** `frontend/src/components/layout/StudentSidebar.jsx`

### 3.1 Import `isHydrated`

On line 33, the existing destructure is:
```js
const { student } = useStudent();
```
Change to:
```js
const { student, isHydrated } = useStudent();
```

### 3.2 Level badge number (line 158)

Current: `{level}`
Change to: `{isHydrated ? level : "—"}`

The level badge is the circular orange div. When `!isHydrated` it shows `—` instead of `1`.

### 3.3 Level label (line 160)

Current: `{t("nav.level", { level, defaultValue: "Level {{level}}" })}`
Change to: `{isHydrated ? t("nav.level", { level }) : "—"}`

### 3.4 XP progress row (lines 166–167)

Current:
```jsx
<span>{t("nav.levelShort", { level })}</span>
<span>{t("nav.xpProgress", { current: xp % 100, max: 100 })}</span>
```
Change to:
```jsx
<span>{isHydrated ? t("nav.levelShort", { level }) : "—"}</span>
<span>{isHydrated ? t("nav.xpProgress", { current: xp % 100, max: 100 }) : "—"}</span>
```

### 3.5 Progress bar (lines 170–174)

The `motion.div` has `animate={{ width: `${xp % 100}%` }}`. When `!isHydrated` force width to `"0%"`:

```jsx
animate={{ width: isHydrated ? `${xp % 100}%` : "0%" }}
```

This is correct — an empty bar is unambiguous. Do not show any non-zero value before hydration.

### 3.6 Day streak (line 177)

The streak block already gates on `dailyStreak >= 1`. Since `dailyStreak` defaults to `0` in the store and is only set by `initAdaptive()`, this section naturally stays hidden until hydration. No additional gate needed.

---

## 4. Fix 1 (cont.) — Skeleton rendering: `DashboardPage.jsx`

**File:** `frontend/src/pages/DashboardPage.jsx`

### 4.1 Import `isHydrated`

On line 41, the existing destructure is:
```js
const { student, masteredConcepts } = useStudent();
```
Change to:
```js
const { student, masteredConcepts, isHydrated } = useStudent();
```

### 4.2 Stats array (lines 153–158)

The second stat entry reads XP and level:
```js
{ icon: Star, label: t("dashboard.toNextLevel", { xp: 100 - (xp % 100), level: level + 1 }), value: `${xp} XP`, ... }
```
Change to:
```js
{
  icon: Star,
  label: isHydrated ? t("dashboard.toNextLevel", { xp: 100 - (xp % 100), level: level + 1 }) : "—",
  value: isHydrated ? `${xp} XP` : "—",
  ...
}
```

The `dailyStreak` stat at index 0 (line 154) also reads from the store but its default `0` is not misleading — a streak of 0 on login is factually plausible and does not produce an obviously wrong display. Leave it ungated unless the product team requests otherwise.

---

## 5. Fix 2 — Age blank on Settings: `teaching_router.py`

**File:** `backend/src/api/teaching_router.py`, lines 287–299.

### 5.1 Change description

The handler at line 287 builds and returns a dict manually. The `age` column is fetched via `db.get(Student, student_id)` but is not included in the return dict.

Add one entry to the dict, after `"preferred_language"`:

```python
"age": student.age,   # int | None — already declared in StudentResponse schema
```

The `StudentResponse` schema (`teaching_schemas.py:56–65`) already declares `age: int | None = None`, so no schema change is needed. The PATCH handler already returns `age` correctly (it serialises via the ORM model through the Pydantic schema).

**After fix**, the dict at lines 287–299 is:
```python
return {
    "id": str(student.id),
    "display_name": student.display_name,
    "interests": student.interests or [],
    "preferred_style": student.preferred_style,
    "preferred_language": student.preferred_language or "en",
    "age": student.age,                         # ← NEW
    "created_at": student.created_at.isoformat(),
    "xp": student.xp,
    "streak": student.streak,
    "daily_streak": student.daily_streak or 0,
    "daily_streak_best": student.daily_streak_best or 0,
    "last_active_date": student.last_active_date.isoformat() if student.last_active_date else None,
}
```

No other files change for this fix. The frontend at `SettingsPage.jsx:136` already binds `setAge(student.age != null ? String(student.age) : "")` — it will populate as soon as the GET response includes `age`.

---

## 6. Fix 3 — Chrome Autofill on Custom Interest Input: `SettingsPage.jsx`

**File:** `frontend/src/pages/SettingsPage.jsx`, lines 296–302.

### 6.1 Current state

```jsx
<input
  value={customInterest}
  onChange={(e) => setCustomInterest(e.target.value)}
  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustomInterest(); } }}
  placeholder={t("customize.addInterest", "Type topic and press Enter...")}
  style={inputStyle}
/>
```

Missing: `type`, `name`, `autoComplete`, `data-lpignore`.

### 6.2 Required attrs

```jsx
<input
  type="text"
  name="custom-interest"
  autoComplete="off"
  data-lpignore="true"
  value={customInterest}
  onChange={(e) => setCustomInterest(e.target.value)}
  onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCustomInterest(); } }}
  placeholder={t("customize.addInterest", "Type topic and press Enter...")}
  style={inputStyle}
/>
```

- `type="text"`: explicit type prevents browser from treating the field as a password or email.
- `name="custom-interest"`: unique name breaks the heuristic Chrome uses to autofill fields with the same name as known fields (`email`, `username`, etc.).
- `autoComplete="off"`: standard signal to the browser. Chrome sometimes ignores it on forms with a real email field, hence the additional attrs.
- `data-lpignore="true"`: LastPass/1Password ignore signal.

No other code change. The `addCustomInterest()` function and `setCustomInterest` state are untouched.

---

## 7. Fix 4 — Logout Confirmation: `AppShell.jsx`

**File:** `frontend/src/components/layout/AppShell.jsx`

### 7.1 Imports to add

At line 1, the existing imports include:
```js
import { useState, useRef, useEffect } from "react";
```
Add `useDialog` import:
```js
import { useDialog } from "../../context/DialogProvider";
```

### 7.2 Hook call inside `AppShell`

`AppShell` is a default-export function component. Inside the component body, add:
```js
const dialog = useDialog();
```
alongside the existing hooks (`useStudent`, `useAuth`, `useTheme`, `useNavigate`, etc.).

### 7.3 Logout handler (lines 358–377)

Current button `onClick`:
```js
onClick={async () => { await logout(); navigate("/login"); }}
```

Replace with:
```js
onClick={async () => {
  const confirmed = await dialog.confirm({
    title: t("confirm.logoutTitle"),
    message: t("confirm.logoutMessage"),
    confirmLabel: t("nav.logout"),
    cancelLabel: t("confirm.cancel"),
    variant: "danger",
  });
  if (!confirmed) return;
  await logout();
  navigate("/login");
}}
```

**State transitions:**
- User clicks logout → `dialog.confirm()` returns a Promise.
- `DialogProvider` opens modal, suspends the async handler.
- User clicks Cancel → `resolverRef.current(false)` → Promise resolves `false` → `if (!confirmed) return` → handler exits, no navigation, no logout.
- User clicks Confirm ("Logout") → `resolverRef.current(true)` → Promise resolves `true` → `logout()` executes → `navigate("/login")`.

### 7.4 Translation keys used

| i18next key | Used for | en.json value |
|-------------|---------|--------------|
| `confirm.logoutTitle` | Modal title | `"Logout?"` |
| `confirm.logoutMessage` | Modal body | `"Are you sure you want to logout?"` |
| `nav.logout` | Confirm button label | `"Logout"` |
| `confirm.cancel` | Cancel button label | must be sourced from `confirm.cancel` (nested inside `confirm: {}` block) |

**Important:** `confirm.cancel` does not exist as a flat key — it is the nested key path `confirm.cancel` inside the object at key `"confirm"` in the locale files. Verify that i18next resolves this correctly. Looking at `en.json:444–449`, the structure is:
```json
"confirm": {
  "leaveSection": "Leave this section?",
  "leaveSectionMessage": "...",
  "cancel": "Cancel",
  "confirm": "Leave"
}
```
i18next resolves `t("confirm.cancel")` → `"Cancel"`. This works today for the session-leave modal in `LearningPage.jsx`. The same resolution will work here.

---

## 8. i18n Audit — Translation Keys

### 8.1 Keys consumed by Fix 4

| Key (i18next path) | Type | All 13 locales present? |
|-------------------|------|------------------------|
| `confirm.logoutTitle` | flat key | Yes (verified: all 13 have it) |
| `confirm.logoutMessage` | flat key | Yes (verified: all 13 have it) |
| `nav.logout` | flat key | Yes (line 9 in en.json; present in all 13) |
| `confirm.cancel` | nested (`confirm.cancel`) | Yes — nested `confirm` block with `cancel` key exists in all 13 |

No new keys need to be written.

### 8.2 Verification command

```bash
for f in frontend/src/locales/*.json; do
  echo "=== $(basename $f) ==="
  python3 -c "
import json, sys
d = json.load(open('$f'))
keys = ['confirm.logoutTitle', 'confirm.logoutMessage', 'nav.logout']
nested = d.get('confirm', {}).get('cancel')
for k in keys:
    print(k, '->', d.get(k, 'MISSING'))
print('confirm.cancel ->', nested or 'MISSING')
"
done
```

Run from `frontend/`.

---

## 9. Sequence Diagrams

### 9.1 Happy path — Login → XP display (Fix 1)

```
User          Browser            AuthContext       StudentContext        adaptiveStore
 │─── submit login ──►│                                                      │
 │                     │─── POST /auth/login ──►│                            │
 │                     │◄── {access_token, user}─┤                            │
 │                     │    setUser(user)        │                            │
 │                     │    navigate("/dashboard")                             │
 │                     │                         │── useEffect [user.student_id]
 │                     │                         │   isHydrated = false
 │                     │                         │── getStudent(id) ──► API   │
 │                     │  [sidebar renders "—"]  │                            │
 │                     │                         │◄── { xp, level, streak }  │
 │                     │                         │── initAdaptive(...)  ──────►│
 │                     │                         │── isHydrated = true        │
 │                     │  [sidebar renders real values]                        │
 │                     │                         │── getStudentMastery(id) ─► API
 │                     │                         │   setLoading(false)        │
```

### 9.2 Logout confirm — happy path (Fix 4)

```
User              AppShell          DialogProvider         StudentContext / AuthContext
 │─ click Logout ─►│                                              │
 │                  │── dialog.confirm({ ... }) ─────────────────►│
 │                  │   (handler suspends, awaiting Promise)       │
 │                  │                                              │── open Modal
 │◄── modal shown ──┤                                              │
 │─ click "Logout" ─┤                                              │
 │                  │                                        resolve(true)
 │                  │◄─ confirmed = true ────────────────────────┤
 │                  │── await logout() ──────────────────────────►│
 │                  │── navigate("/login")                         │
```

### 9.3 Logout confirm — cancel path (Fix 4)

```
User              AppShell          DialogProvider
 │─ click Logout ─►│                     │
 │                  │── dialog.confirm() ─►│── open Modal
 │◄── modal shown ──┤                     │
 │─ click Cancel ───┤                     │
 │                  │               resolve(false)
 │                  │◄─ confirmed = false─┤
 │                  │   return (no-op)    │
 │                  │                     │ (modal closed, no navigation)
```

---

## 10. Security Design

- **Fix 3 (autofill):** Browser autofill with email addresses in an interest field is a data-integrity concern, not a security vector. The attrs added are standard suppression signals with no security downside.
- **Fix 4 (logout confirm):** The confirmation modal does not add or remove any authentication surface. It only delays the handler by one user action. The `DialogProvider.confirm()` API uses in-memory Promise resolution — no persistence, no network call.
- All other fixes are read-path or display-only changes with no security implications.

---

## 11. Observability Design

No new logging, metrics, or tracing needed. The changes are all synchronous UI state transitions. Existing `console.error("[StudentContext] Failed to load student:", err)` on the catch path remains unchanged — the `isHydrated` flag staying `false` on error is the observable signal.

---

## 12. Error Handling and Resilience

| Scenario | Behavior |
|----------|---------|
| `getStudent()` fails (network error) | `isHydrated` remains `false`. Skeleton placeholders stay visible. Existing error log fires. No regression from current behaviour. |
| `dialog.confirm()` called when `DialogProvider` not in tree | `useDialog()` returns `null`; `.confirm(...)` throws. Mitigated by `DialogProvider` being mounted at root (`App.jsx:140`). No guard needed in `AppShell`. |
| Backend returns `age: null` for a student who never set it | `SettingsPage` already handles `student.age != null ? String(student.age) : ""` at line 136 — field stays blank, correct. |
| `isHydrated` stuck `false` after rapid logout/re-login | Effect dependency on `user?.student_id` ensures re-execution on any user change. Reset and re-hydration are triggered correctly. |

---

## 13. Testing Strategy

### 13.1 Backend — `backend/tests/test_api_integration.py`

Add one assertion to the existing `TestStudentEndpoints` class. Find the test at line 229 (`test_get_student_with_valid_uuid_returns_data`) or add a new test method:

```
test_get_student_includes_age_field:
  1. PATCH /api/v2/students/{id} with { "age": 22 } → assert 200
  2. GET /api/v2/students/{id} → assert response["age"] == 22
  3. PATCH /api/v2/students/{id} with { "age": null } → assert 200
  4. GET /api/v2/students/{id} → assert response["age"] is None
```

This is a round-trip assertion covering both set and clear.

### 13.2 Playwright e2e — `frontend/tests/e2e/ux-fixes.spec.js` (new file)

Two test blocks:

**Block 1 — XP skeleton**
```
1. Navigate to /login, submit valid credentials.
2. After navigation to /dashboard, before any API response settles:
   - Assert sidebar level badge text is "—" OR assert XP text is "—"
   (Use Playwright's fast selector with short timeout, or intercept getStudent XP.)
3. After getStudent resolves (wait for network idle):
   - Assert sidebar level badge is a number >= 1.
   - Assert XP text matches /\d+ XP/.
```

Note: The race window is small. The test can mock the `GET /api/v2/students/{id}` route in Playwright to add a 300ms delay, ensuring the skeleton is visible before assertions.

**Block 2 — Logout confirm**
```
1. Login, navigate to authenticated route.
2. Click logout button in sidebar.
3. Assert confirm modal is visible (look for t("confirm.logoutTitle") text).
4. Click Cancel button.
5. Assert URL is still /dashboard (no navigation).
6. Click logout button again.
7. Click Confirm ("Logout") button.
8. Assert URL is /login.
```

### 13.3 Manual checks

- Open Settings after PATCH with an age value → confirm age field is pre-populated.
- Focus custom-interest input → confirm Chrome does not inject email.
- Collapse sidebar → confirm `—` is not visible in collapsed mode (collapsed mode shows only the avatar initial, not XP text — no gate needed there).

---

## Key Decisions Requiring Stakeholder Input

1. **`dailyStreak` skeleton gate:** The streak row hides when `dailyStreak === 0` by existing logic. If a student with a real streak logs in, they will briefly see no streak row, then it appears. This is acceptable (streak = 0 is the store default; the gate is implicit). Confirm this is acceptable before closing the ticket.
2. **Playwright test setup:** The project has no `frontend/tests/e2e/` directory. The `playwright.config.js` may need to be created or extended. Confirm the test runner target with the frontend-developer before Step 2 begins (see execution plan).
3. **`confirm.cancel` key path:** The Dialog component currently hardcodes `"Cancel"` as the default `cancelLabel`. The `AppShell` logout handler should pass `t("confirm.cancel")` explicitly so the label is localised. Confirm that the product team accepts "Cancel" as the universal label across all 13 languages (existing translations confirm this — e.g., ar: "إلغاء").

---

## Follow-ups v2 — Custom interests persistence, LLM validation, per-card rotation

**Date:** 2026-04-23 (continuation)
**Plan:** `~/.claude/plans/problems-why-is-the-tranquil-pie.md`

### Problems addressed
1. `SettingsPage.jsx:483` (Account-section Logout) missed by first-round fix → still no confirm.
2. Chrome autofill still injects the student's gmail into the custom-interest input despite `autoComplete="off"` etc. Field-level off is ignored when a real email field exists nearby.
3. `interests` column conflates "known" and "currently-selected" — deselecting a custom interest erases the chip. Split it.
4. Gibberish typed interest (`hfjsd`) passes format validation and poisons LLM prompts. Requires semantic gating.
5. Multi-interest framing hardcodes first element at `prompts.py:79-88`. Only `fruits` ever frames examples when `[fruits, sports, gaming]` are selected. Rotate per card.

### Schema (additive, non-breaking)
- New column on `Student`: `custom_interests: JSON, NOT NULL, server_default='[]'`. Pattern mirrors the existing `interests` column.
- Alembic migration auto-generated; verify `server_default=sa.text("'[]'")` so existing rows backfill cleanly rather than NULL.
- `interests` keeps its semantics — **currently selected** (feeds LLM prompt). `custom_interests` is a **superset of known customs** (drives UI rendering).

### Validation contract (both client- and server-side)
Order is cheapest-first. Server is authoritative; client mirrors for UX.
1. Format — trim; length 2–30; regex `/^[\p{L}\s-]+$/u` (Unicode letters, spaces, hyphens); case-insensitive dedupe against predefined `INTEREST_OPTIONS` ids + existing `custom_interests`; cap 20 per student.
2. LLM — run only if (1) passes. Prompts a cheap model (`OPENAI_MODEL_MINI`) with "Is `<text>` a recognizable personal interest in any language? Reply JSON `{ok:bool, reason:str}`". Fail-closed: unreachable LLM or malformed JSON → reject with "Validation service unavailable" (bias toward false-reject for lesson quality).
3. In-process TTL cache keyed on `(normalized_text.lower(), language)`, TTL = `INTEREST_VALIDATOR_CACHE_TTL_SECONDS` (1 hour default). Prevents re-billing same-word retries.

PATCH `/api/v2/students/{id}/profile` re-runs full validation server-side for defence in depth, **skipping LLM for strings already in the student's existing `custom_interests`** (trusted).

### New endpoint
`POST /api/v2/students/{id}/custom-interests/validate`
- Body: `{text: str, language?: str}`; language defaults to `student.preferred_language`.
- Auth: `get_current_user` + `_validate_student_ownership`.
- Response: `{ok: bool, reason: str | None, normalized: str}`. Always HTTP 200; `ok=false` carries the reason in the body.
- Rate-limited via existing limiter decorator (match neighboring endpoints).

### Per-card rotation contract
- `_build_interests_block(interests, primary=None)` — `primary` is used for the single "frame every example using: X context" line. Falls back to `interests[0]` when `None` (preserves current behavior for lesson-wide prompts).
- Every prompt builder in `prompts.py` that currently takes `interests` gains a `primary_interest: str | None = None` parameter, threaded through.
- `teaching_service.generate_per_card()` computes `primary = lesson_interests[card_index % len(lesson_interests)] if lesson_interests else None` and passes it down. Rotation reads from the **session-locked** `lesson_interests`, not from live `student.interests` (preserves the CLAUDE.md gotcha: mid-session Settings changes return 409).
- **`cache_version` bumps from 1 → 2** in `teaching_service.py` (two occurrences: lines 656, 709). This invalidates pre-existing per-card cache entries that were rendered under the old single-primary behavior.

### New i18n keys (all 13 locales)
- `settings.interestTooShort`, `settings.interestTooLong`, `settings.interestInvalid`
- `settings.interestAlreadyPredefined`, `settings.interestDuplicate`, `settings.interestLimit`
- `settings.interestUnrecognized`, `settings.interestValidatorUnavailable`
- `settings.deleteCustomInterest` (aria-label), `settings.validating` (spinner caption)

Actual translations required — no English fallbacks.

### Constants (backend/src/config.py)
- `INTEREST_VALIDATOR_MODEL` — reuse `OPENAI_MODEL_MINI` value (cheapest capable model already in the stack).
- `INTEREST_MIN_LENGTH = 2`, `INTEREST_MAX_LENGTH = 30`
- `CUSTOM_INTERESTS_MAX = 20`
- `INTEREST_VALIDATOR_CACHE_TTL_SECONDS = 3600`

### UI contract (SettingsPage.jsx)
- Account-section Logout: same `useDialog().confirm({ variant: "danger" })` as the sidebar, using existing translation keys.
- Custom-interest input: `autoComplete="new-password"` (Chrome-kill-switch) + `role="textbox"` (prevents screen-reader confusion) + comment explaining the hack.
- New `customInterests` state hydrated from `student.custom_interests`.
- Custom chips render identically to predefined chips: orange/selected when in `interests`, grey/unselected otherwise. Clicking toggles `interests` membership; chip persists regardless.
- Small trash icon on each custom chip deletes from both `customInterests` and `interests`. No confirm — low stakes.
- `handleSavePrefs` flushes any pending `customInterest` text through both-stage validation before PATCH; submits both `interests` and `custom_interests`.
- Inline `interestErr` slot below the input shows validator errors; cleared on typing.

### Out of scope (explicit)
- AdminSidebar logout — has its own inline modal, untouched.
- Sidebar logout in AppShell — already gated in previous fix.
- Backend migration of existing `interests` column data into `custom_interests` — new field starts empty; existing customs already in `interests` become selectable chips via a frontend hydration fallback (if `student.custom_interests` is empty but `student.interests` contains strings not in `INTEREST_OPTIONS`, treat those as known customs for display purposes only). Decided against a one-shot backfill migration to keep the migration reversible.
