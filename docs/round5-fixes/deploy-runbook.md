# Round 5 Deploy Runbook

**Type**: Backend-only (pure code, no migrations, no frontend rebuild)  
**Commits**: 5 (152f59a → 53afb5c → d87aa87 → 0530077 → 19ff35c)  
**Date**: 2026-04-28

---

## Pre-deploy Checklist

Run these via SSH before touching anything:

```bash
# 1. Capture current image SHA for rollback
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker inspect ada-backend-1 --format '{{.Image}}'"
# Save this output — you will need it if rollback is required.

# 2. Confirm no books are in PROCESSING state
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker exec ada-backend-1 psql \$DATABASE_URL -c \
   \"SELECT slug, status FROM books WHERE status = 'PROCESSING';\""
# Expected: 0 rows. If any row is returned, STOP — wait for processing to finish.

# 3. Confirm no active pipeline_runner containers
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker ps --filter name=pipeline --format '{{.Names}} {{.Status}}'"
# Expected: empty or all Exited. Any Up row = active pipeline — STOP.

# 4. Note current backend uptime (for post-deploy comparison)
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker ps --filter name=ada-backend-1 --format '{{.Status}}'"
```

---

## Deploy Command Sequence

**Step 0 (local):** Push your 5 commits first — the server pulls from origin.

```bash
git push origin main
```

**Step 1 (server):** Pull, rebuild backend, restart.

```bash
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 << 'EOF'
set -euo pipefail
cd ~/ADA

echo "=== Pulling latest ==="
git pull origin main

echo "=== Confirming 5 commits landed ==="
git log --oneline -5

echo "=== Building backend image ==="
docker compose build backend

echo "=== Restarting backend ==="
docker compose up -d backend

echo "=== Waiting for startup ==="
sleep 15

echo "=== Tail logs ==="
docker compose logs --tail=30 backend
EOF
```

Expected in logs: `Application startup complete` with no `ERROR` lines and no `ImportError` / `AttributeError` tracebacks.

---

## Verification Checks

Run each block after the restart log shows a clean startup.

### 1. Container health

```bash
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker ps --filter name=ada-backend-1 --format '{{.Names}} {{.Status}}'"
# Expected: ada-backend-1   Up X seconds
```

### 2. All 5 books still PUBLISHED

```bash
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker exec ada-backend-1 psql \$DATABASE_URL -c \
   \"SELECT slug, status FROM books ORDER BY slug;\""
# Expected: 5 rows, all status = PUBLISHED
```

### 3. is_hidden smoke test — concept map endpoint

```bash
curl -s "https://adaptivelearner.hightekers.com/api/v1/graph/full?book_slug=introduction_to_philosophy" \
  | python3 -c "
import json, sys
data = json.load(sys.stdin)
nodes = data.get('nodes', [])
hidden = [n for n in nodes if n.get('id','').endswith('1.1') or 'What Is Philosophy' in n.get('label','')]
visible = [n for n in nodes if 'philosophy' in n.get('id','').lower()]
print(f'Total philosophy nodes: {len(visible)}')
print(f'Nodes matching 1.1 / What Is Philosophy: {hidden}')
print('PASS: section 1.1 absent' if not hidden else 'FAIL: section 1.1 still present')
"
```

Expected: `PASS: section 1.1 absent` and zero matching nodes in the hidden list.

### 4. AdminConfig live-read spot check (CHUNK_EXAM_PASS_RATE)

```bash
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker exec ada-backend-1 psql \$DATABASE_URL -c \
   \"SELECT key, value FROM admin_config WHERE key IN ('chunk_exam_pass_rate','openai_model','openai_model_mini');\""
# Confirms the rows exist; backend reads them at call time (no restart required for config changes).
```

---

## Rollback Plan

Use this if the backend fails to start or smoke tests fail.

### Option A — Git revert and rebuild (preferred, leaves audit trail)

```bash
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 << 'EOF'
set -euo pipefail
cd ~/ADA
git revert --no-commit 19ff35c 0530077 d87aa87 53afb5c 152f59a
git commit -m "Revert: Round 5 deploy (emergency rollback)"
docker compose build backend
docker compose up -d backend
sleep 15
docker compose logs --tail=20 backend
EOF
# Then push the revert commit from local: git pull && git push origin main
```

### Option B — Previous image SHA (fastest, no git change)

```bash
# Replace <PREVIOUS_SHA> with the image SHA captured in the pre-deploy checklist.
ssh -i ~/Documents/ada-key.pem ubuntu@54.198.132.109 \
  "docker stop ada-backend-1 && \
   docker run -d --name ada-backend-1 \
     --network ada_default \
     --env-file ~/ADA/.env \
     -p 8889:8889 \
     <PREVIOUS_SHA>"
```

Note: Option B is a stop-gap only. Follow up with Option A to get git history back in sync.

---

## Risk Register

### Risk 1 — `get_admin_config` DB call fails at startup if `admin_config` table is empty or missing the expected keys

**Likelihood**: Low — table and keys were verified during dev. **Impact**: Medium — any endpoint that calls `get_admin_config` will fall back to `config.py` defaults (per the fallback logic in commit 19ff35c), so the backend stays up. Affected behaviour: pass rate and model selections revert to static defaults until rows are inserted.  
**Mitigation**: The verification check (Step 4) confirms the rows are present immediately after restart.

### Risk 2 — is_hidden filter (commit 0530077) silently hides more chunks than intended if `is_hidden` was set on non-philosophy sections by an admin during the pipeline run window

**Likelihood**: Low — no books were in PROCESSING at deploy time. **Impact**: High — students would see an incomplete concept map with no error.  
**Mitigation**: The smoke test (Step 3) checks one known-hidden section. Additionally, run `SELECT concept_id FROM concept_chunks WHERE is_hidden = true` after deploy to enumerate all hidden chunks and confirm the list matches expectations.

### Risk 3 — `translate_catalog` per-language commit change (commit d87aa87) triggers a partial re-translate on next startup if the catalog file was written mid-run during the last session

**Likelihood**: Low — clinical_nursing_skills was fully published at 13:45 UTC before this deploy. **Impact**: Low — worst case is redundant OpenAI translation API calls; no data corruption. The per-language commit logic is idempotent.  
**Mitigation**: Watch backend logs for `[translate_catalog]` lines during the first 60 seconds after restart. If translation calls appear unexpectedly, they will complete without error and will not recur on the next restart.
