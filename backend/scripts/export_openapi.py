"""Write backend/openapi.json from the app factory without touching a database."""
from __future__ import annotations

import json
from pathlib import Path

from vocal_coach.config import load_config
from vocal_coach.jobs.runner import JobRunner, SyncExecutor
from vocal_coach.main import create_app
from vocal_coach.settings import Settings
from vocal_coach.storage.db import make_engine

OUT = Path(__file__).resolve().parents[1] / "openapi.json"

settings = Settings(_env_file=None, database_url="sqlite+pysqlite:///:memory:", require_ffmpeg=False)
cfg = load_config()
app = create_app(settings, cfg, engine=make_engine(settings.database_url),
                 runner=JobRunner(settings, cfg, executor=SyncExecutor()), run_migrations=False)
OUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n")
print(f"wrote {OUT}")
