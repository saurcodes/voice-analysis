#!/usr/bin/env bash
# Bring the stack up, obtain a token for the demo user, hit /api/me, upload a WAV, wait for the job.
# Needs the dev realm (keycloak/realm-export.dev.json, the compose default): demo user + password grant.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose up -d --build
echo "waiting for backend…"
for _ in $(seq 1 60); do curl -fsS http://localhost:8000/docs >/dev/null 2>&1 && break; sleep 2; done
TOKEN=$(curl -fsS -X POST http://localhost:8080/realms/vocal-coach/protocol/openid-connect/token \
  -d client_id=vocal-coach-web -d grant_type=password -d username=demo -d password=demo | python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
ME=$(curl -fsS http://localhost:8000/api/me -H "Authorization: Bearer $TOKEN")
echo "$ME"
echo "$ME" | python3 -c 'import sys,json;d=json.load(sys.stdin);print("drive:",d.get("drive_configured"),d.get("drive_connected"),d.get("google_email"))'
WAV=${1:-}
if [ -n "$WAV" ]; then
  JOB=$(curl -fsS -X POST http://localhost:8000/api/analyses -H "Authorization: Bearer $TOKEN" -F "file=@$WAV" | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_ids"][0])')
  echo "job $JOB"
  curl -NsS "http://localhost:8000/api/jobs/$JOB/events" -H "Authorization: Bearer $TOKEN"
fi
