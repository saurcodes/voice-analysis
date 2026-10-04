"""Build a fully wired FastAPI app on SQLite with a synchronous fake job runner."""
from __future__ import annotations

import copy
import functools
import json
import tempfile
from pathlib import Path

from tests import synth
from tests.auth_keys import make_rsa_jwks, mint
from vocal_coach.auth.jwt import JWKSCache
from vocal_coach.config import load_config
from vocal_coach.jobs.runner import JobRunner, SyncExecutor
from vocal_coach.main import create_app
from vocal_coach.settings import Settings
from vocal_coach.storage.db import create_all, make_engine, make_session_factory

ISS = "http://kc.test/realms/vocal-coach"
AUD = "vocal-coach-web"


def make_test_app(tmp_path: Path, *, job_fn=None, max_upload_mb: int = 500):
    pem, jwks, kid = make_rsa_jwks()
    settings = Settings(_env_file=None, database_url=f"sqlite+pysqlite:///{tmp_path / 't.db'}",
                        keycloak_issuer=ISS, keycloak_audience=AUD, data_dir=tmp_path / "data",
                        max_upload_mb=max_upload_mb, require_ffmpeg=False, job_workers=1)
    cfg = load_config()
    engine = make_engine(settings.database_url)
    create_all(engine)
    runner = JobRunner(settings, cfg, executor=SyncExecutor(), job_fn=job_fn)
    app = create_app(settings, cfg, engine=engine, runner=runner,
                     jwks=JWKSCache(settings.jwks_url, fetch=lambda url: jwks, min_refresh_interval_s=0.0),
                     run_migrations=False)
    ctx = {
        "pem": pem, "kid": kid, "iss": ISS, "aud": AUD, "settings": settings, "cfg": cfg,
        "session_factory": make_session_factory(engine),
        "token": lambda sub="user-1", **kw: mint(pem, kid, iss=ISS, aud=AUD, sub=sub, **kw),
    }
    ctx["auth"] = lambda sub="user-1": {"Authorization": f"Bearer {ctx['token'](sub)}"}
    return app, ctx


@functools.lru_cache(maxsize=1)
def _real_report() -> str:
    """One real MetricsReport (canonical JSON) from a synthetic 4 s vowel, computed once per test session."""
    from vocal_coach.analysis.analyser import analyse_wav
    from vocal_coach.analysis.schema import SourceInfo
    from vocal_coach.analysis.serialise import to_canonical_json

    with tempfile.TemporaryDirectory() as d:
        wav = synth.write_wav(Path(d) / "v.wav", synth.with_noise_floor(synth.am(synth.vowel(500, 1500, 120, 4.0), 4.0)))
        source = SourceInfo(file_name="v.wav", drive_file_id=None, drive_modified_time=None, content_sha256="0" * 64,
                            duration_s=4.0, original_channels=1, original_sample_rate=synth.SR)
        return to_canonical_json(analyse_wav(wav, load_config(), source))


def fake_metrics(**headline) -> dict:
    """A schema-valid metrics_json with known headline values (the API types it as MetricsReport)."""
    m = copy.deepcopy(json.loads(_real_report()))
    m["pitch"]["f0_median_hz"] = headline.get("f0_median_hz", 123.0)
    m["pitch"]["f0_range_st"] = headline.get("f0_range_st", 9.0)
    m["phrasing"]["pauses_per_min"] = headline.get("pauses_per_min", 10.0)
    m["intonation"]["flat_pct"] = headline.get("flat_pct", 30.0)
    m["pace"]["articulation_rate_syl_per_sec"] = headline.get("articulation_rate_syl_per_sec", 4.0)
    m["energy"]["trailing_off_count"] = headline.get("trailing_off_count", 2)
    return m


def fake_transcript(text: str = "hi", fillers_per_min: float = 1.5) -> dict:
    """A schema-valid transcript_json (the API types it as Transcript)."""
    return {
        "schema_version": "1.0", "model": "fake", "language": "en", "text": text, "segments": [], "words": [],
        "derived": {
            "word_count": 1, "words_per_min": 60.0, "filler_counts": {}, "filler_total": 0,
            "fillers_per_min": fillers_per_min,
            "clarity": {"low_conf_word_fraction": None, "low_conf_words": [], "word_final_drop_count": 0,
                        "word_final_drop_fraction": None, "eaten_words": [], "rushed_word_fraction": None,
                        "rushed_runs": [], "segment_avg_logprob_mean": None, "low_logprob_segment_fraction": None},
        },
    }
