import json
import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import _upload, fake_job_fn, failing_job_fn
from vocal_coach.storage import repo


def _events(resp):
    out, event = [], {}
    for line in resp.iter_lines():
        if line.startswith("event:"):
            event["event"] = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            event["data"] = json.loads(line.split(":", 1)[1].strip())
        elif line == "" and event:
            out.append(event); event = {}
    return out


def test_sse_on_finished_job_emits_terminal_event_and_closes(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        with client.stream("GET", f"/api/jobs/{job_id}/events", headers=ctx["auth"]()) as resp:
            assert resp.status_code == 200
            events = _events(resp)
    kinds = [e["event"] for e in events]
    assert kinds[-1] == "done" and events[-1]["data"]["analysis_id"]
    assert "stage" in kinds and "progress" in kinds


def test_sse_failed_job_emits_error(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=failing_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        with client.stream("GET", f"/api/jobs/{job_id}/events", headers=ctx["auth"]()) as resp:
            events = _events(resp)
    assert events[-1]["event"] == "error" and events[-1]["data"]["message"] == "boom"


def test_sse_foreign_job_is_404(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        job_id = _upload(client, ctx["auth"]("alice")).json()["job_ids"][0]
        assert client.get(f"/api/jobs/{job_id}/events", headers=ctx["auth"]("bob")).status_code == 404
        assert client.get(f"/api/jobs/{uuid.uuid4()}/events", headers=ctx["auth"]("alice")).status_code == 404


def test_job_events_generator_streams_progress(tmp_path):
    """Drive the generator directly: a running job that is advanced between polls."""
    import asyncio
    from vocal_coach.jobs.events import job_events

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    factory = ctx["session_factory"]
    with factory() as s:
        user = repo.upsert_user(s, "u", None, None)
        job = repo.create_job(s, user.id)

    async def run():
        gen = job_events(factory, user.id, job.id, poll_interval_s=0.01)
        seen = []
        seen.append(await gen.__anext__())  # initial stage
        with factory() as s:
            repo.update_job(s, job.id, status="running", stage="analyse", progress_pct=55)
        seen.append(await gen.__anext__())
        seen.append(await gen.__anext__())
        with factory() as s:
            repo.update_job(s, job.id, status="done", stage="done", progress_pct=100)
        async for e in gen:
            seen.append(e)
        return seen

    seen = asyncio.run(run())
    kinds = [e["event"] for e in seen]
    assert kinds[0] == "stage" and "progress" in kinds and kinds[-1] == "done"
