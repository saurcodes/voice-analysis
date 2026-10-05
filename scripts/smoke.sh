#!/usr/bin/env bash
# End-to-end smoke test against the compose stack:
#   bring up -> wait for backend -> token -> /api/me -> upload a generated WAV -> poll the job
#   -> fetch the analysis -> compare the two most recent analyses -> /api/llm/models.
# Needs the dev realm (keycloak/realm-export.dev.json, the compose default): demo user + password grant.
#
# Environment:
#   SMOKE_NO_UP=1          skip `docker compose up -d --build` (stack already running)
#   SMOKE_TIMEOUT_S=180    how long to wait for the analysis job (the first job in a fresh
#                          stack also downloads the whisper model, about 460 MB)
#   API_URL                backend base URL (default http://localhost:8000)
#   KEYCLOAK_URL           Keycloak base URL (default http://localhost:8080)
#   SMOKE_USER / SMOKE_PASSWORD   credentials for the password grant (default demo / demo)
set -euo pipefail
cd "$(dirname "$0")/.."

API_URL=${API_URL:-http://localhost:8000}
KEYCLOAK_URL=${KEYCLOAK_URL:-http://localhost:8080}
SMOKE_USER=${SMOKE_USER:-demo}
SMOKE_PASSWORD=${SMOKE_PASSWORD:-demo}
SMOKE_TIMEOUT_S=${SMOKE_TIMEOUT_S:-180}

fail() { echo "FAIL: $*" >&2; exit 1; }
step() { echo; echo "== $*"; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# 1. Bring the stack up.
if [ "${SMOKE_NO_UP:-}" = "1" ]; then
  step "skipping docker compose up (SMOKE_NO_UP=1)"
else
  step "docker compose up -d --build"
  docker compose up -d --build
fi

# 2. Wait for the backend.
step "waiting for the backend at $API_URL"
ready=0
for _ in $(seq 1 90); do
  if curl -fsS "$API_URL/openapi.json" >/dev/null 2>&1; then ready=1; break; fi
  sleep 2
done
[ "$ready" = "1" ] || fail "backend did not answer $API_URL/openapi.json within 180 s"
echo "backend is up"

# 3. Token from Keycloak (password grant, dev realm only).
step "token for $SMOKE_USER"
TOKEN=$(curl -fsS -X POST "$KEYCLOAK_URL/realms/vocal-coach/protocol/openid-connect/token" \
  -d client_id=vocal-coach-web -d grant_type=password \
  -d "username=$SMOKE_USER" -d "password=$SMOKE_PASSWORD" \
  | python3 -c 'import sys, json; print(json.load(sys.stdin)["access_token"])') \
  || fail "could not get a token (is the dev realm imported?)"
AUTH=(-H "Authorization: Bearer $TOKEN")
echo "got a token"

# 4. /api/me with the drive and llm flags.
step "GET /api/me"
curl -fsS "${AUTH[@]}" "$API_URL/api/me" > "$WORK/me.json" || fail "/api/me failed"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print("user:", d.get("username"), d.get("email"))
print("drive: configured=%s connected=%s google_email=%s" % (d.get("drive_configured"), d.get("drive_connected"), d.get("google_email")))
print("llm: enabled=%s provider=%s" % (d.get("llm_enabled"), d.get("llm_provider")))
' "$WORK/me.json"

# 5. Generate a 3-second 16 kHz sine WAV.
step "generating a 3 s 16 kHz sine WAV"
WAV="$WORK/smoke-sine.wav"
python3 -c '
import math, struct, sys, wave
rate, seconds, freq = 16000, 3, 150.0
frames = b"".join(
    struct.pack("<h", int(0.5 * 32767 * math.sin(2 * math.pi * freq * i / rate)))
    for i in range(rate * seconds)
)
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(rate)
    w.writeframes(frames)
' "$WAV"
echo "wrote $WAV"

# 6. Upload it (coaching off, so the smoke run does not depend on an LLM).
step "POST /api/analyses (multipart upload)"
curl -fsS -X POST "${AUTH[@]}" -F "file=@$WAV;type=audio/wav" -F llm_enabled=false \
  "$API_URL/api/analyses" > "$WORK/upload.json" || fail "upload failed"
JOB=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["job_ids"][0])' "$WORK/upload.json")
echo "job $JOB"

# 7. Poll the job every 2 s until done or failed.
step "polling GET /api/jobs/$JOB (up to ${SMOKE_TIMEOUT_S} s)"
ANALYSIS=""
deadline=$(( $(date +%s) + SMOKE_TIMEOUT_S ))
while :; do
  curl -fsS "${AUTH[@]}" "$API_URL/api/jobs/$JOB" > "$WORK/job.json" || fail "GET /api/jobs/$JOB failed"
  LINE=$(python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print(d["status"], d.get("stage") or "-", d.get("progress_pct") or 0)
' "$WORK/job.json") || fail "unexpected job response: $(cat "$WORK/job.json")"
  read -r STATUS STAGE PCT <<< "$LINE"
  echo "status=$STATUS stage=$STAGE progress=$PCT%"
  if [ "$STATUS" = "done" ]; then
    ANALYSIS=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["analysis_id"])' "$WORK/job.json")
    break
  fi
  if [ "$STATUS" = "failed" ]; then
    ERR=$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1])).get("error"))' "$WORK/job.json")
    fail "job $JOB failed: $ERR"
  fi
  [ "$(date +%s)" -lt "$deadline" ] || fail "job $JOB not finished after ${SMOKE_TIMEOUT_S} s (status $STATUS)"
  sleep 2
done
echo "analysis $ANALYSIS"

# 8. Fetch the analysis.
step "GET /api/analyses/$ANALYSIS"
curl -fsS "${AUTH[@]}" "$API_URL/api/analyses/$ANALYSIS" > "$WORK/analysis.json" || fail "GET /api/analyses/$ANALYSIS failed"
python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
m = d["metrics"]
print("file:", d.get("file_name"))
print("pitch.f0_median_hz:", (m.get("pitch") or {}).get("f0_median_hz"))
print("recording_quality.reasons:", (m.get("recording_quality") or {}).get("reasons"))
' "$WORK/analysis.json"

# 9. Compare the two most recent analyses, when there are two.
step "GET /api/analyses?limit=2"
curl -fsS "${AUTH[@]}" "$API_URL/api/analyses?limit=2" > "$WORK/list.json" || fail "GET /api/analyses failed"
IDS=$(python3 -c 'import json, sys; print(",".join(a["id"] for a in json.load(open(sys.argv[1]))))' "$WORK/list.json")
if [[ "$IDS" == *,* ]]; then
  step "GET /api/comparisons?ids=$IDS"
  curl -fsS "${AUTH[@]}" "$API_URL/api/comparisons?ids=$IDS" > "$WORK/comparison.json" || fail "comparison failed"
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print("comparison rows:", len(d["rows"]), "config_mismatch:", d.get("config_mismatch"))
' "$WORK/comparison.json"
else
  echo "only one analysis stored; skipping the comparison"
fi

# 10. LLM models (informational: a 503 from an unreachable provider does not fail the run).
step "GET /api/llm/models"
CODE=$(curl -sS -o "$WORK/models.json" -w '%{http_code}' "${AUTH[@]}" "$API_URL/api/llm/models") \
  || fail "GET /api/llm/models did not answer"
if [ "$CODE" = "200" ]; then
  python3 -c '
import json, sys
d = json.load(open(sys.argv[1]))
print("llm: enabled=%s provider=%s models=%s" % (d.get("enabled"), d.get("provider"), d.get("models")))
' "$WORK/models.json"
elif [ "$CODE" = "503" ]; then
  python3 -c '
import json, sys
print("llm provider unavailable (503):", json.load(open(sys.argv[1])).get("detail"))
' "$WORK/models.json"
else
  fail "GET /api/llm/models answered HTTP $CODE"
fi

echo
echo "SMOKE OK"
