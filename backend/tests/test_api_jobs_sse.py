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


def test_job_events_generator_times_out_with_timeout_event(tmp_path):
    """The stream cap is not an error: the terminal event is `timeout`, and the client falls back to polling."""
    import asyncio
    from vocal_coach.jobs.events import job_events

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    factory = ctx["session_factory"]
    with factory() as s:
        user = repo.upsert_user(s, "u", None, None)
        job = repo.create_job(s, user.id)
        repo.update_job(s, job.id, status="running", stage="analyse", progress_pct=40)

    async def run():
        return [e async for e in job_events(factory, user.id, job.id, poll_interval_s=0.01, max_duration_s=0.0)]

    seen = asyncio.run(run())
    assert seen[-1]["event"] == "timeout" and "poll GET /api/jobs/" in json.loads(seen[-1]["data"])["message"]
    assert "error" not in [e["event"] for e in seen]


def running_job_fn(req, database_url, config_path):
    """Leave the job mid-pipeline (running/analyse/40) without finishing it."""
    from vocal_coach.storage.db import make_engine, make_session_factory
    engine = make_engine(database_url)
    with make_session_factory(engine)() as s:
        repo.update_job(s, req.job_id, status="running", stage="analyse", progress_pct=40)
    engine.dispose()


def test_open_sse_stream_holds_no_pooled_connection(tmp_path):
    """Drive the ASGI app directly so the stream stays open while we inspect the pool (TestClient buffers
    the whole response, which would never end for a running job)."""
    import asyncio

    app, ctx = make_test_app(tmp_path, job_fn=running_job_fn)
    with TestClient(app) as client:  # runs the lifespan; app.state is wired
        job_id = _upload(client, ctx["auth"]()).json()["job_ids"][0]
        engine = app.state.engine
        token = ctx["token"]()
        path = f"/api/jobs/{job_id}/events"

        async def run():
            chunks: asyncio.Queue[bytes] = asyncio.Queue()
            disconnect = asyncio.Event()
            sent_request = False

            async def receive():
                nonlocal sent_request
                if not sent_request:
                    sent_request = True
                    return {"type": "http.request", "body": b"", "more_body": False}
                await disconnect.wait()
                return {"type": "http.disconnect"}

            async def send(message):
                if message["type"] == "http.response.start":
                    assert message["status"] == 200
                elif message["type"] == "http.response.body" and message.get("body"):
                    await chunks.put(message["body"])

            scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
                     "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"", "root_path": "",
                     "server": ("test", 80), "client": ("test", 1), "app": app,
                     "headers": [(b"host", b"test"), (b"authorization", f"Bearer {token}".encode())]}
            task = asyncio.create_task(app(scope, receive, send))

            async def next_event() -> str:
                buf = ""
                while "\r\n\r\n" not in buf and "\n\n" not in buf:
                    buf += (await asyncio.wait_for(chunks.get(), timeout=5)).decode()
                return buf

            first, second = await next_event(), await next_event()
            assert "event: stage" in first and "event: progress" in second
            await asyncio.sleep(0.6)  # at least one more poll cycle while the stream is open
            checked_out = engine.pool.checkedout()
            with ctx["session_factory"]() as s:
                repo.update_job(s, uuid.UUID(job_id), status="done", stage="done", progress_pct=100)
            tail = ""
            while "event: done" not in tail:
                tail += await next_event()
            await asyncio.wait_for(task, timeout=5)
            disconnect.set()
            return checked_out, tail

        checked_out, tail = asyncio.run(run())
    assert checked_out == 0
    assert "event: done" in tail


def test_postgres_engine_pool_size():
    from vocal_coach.storage.db import POOL_SIZE, make_engine
    engine = make_engine("postgresql+psycopg://u:p@localhost:1/x")  # no connection is made until first use
    assert engine.pool.size() == POOL_SIZE and engine.pool._pre_ping is True
