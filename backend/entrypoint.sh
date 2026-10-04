#!/usr/bin/env sh
set -eu
# Migrations run once here, in a single process, before uvicorn starts (spec §14; Plan 3 note).
python -c "import os; from vocal_coach.storage.migrate import upgrade_to_head; upgrade_to_head(os.environ['DATABASE_URL'])"
exec uvicorn "vocal_coach.main:create_app" --factory --host 0.0.0.0 --port 8000 --workers 1
