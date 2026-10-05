import uuid

from fastapi.testclient import TestClient

from tests.api_fixtures import make_test_app
from tests.test_api_analyses import _upload, _wav_bytes, fake_job_fn


def _ids(client, headers, n):
    out = []
    for i in range(n):
        job_id = _upload(client, headers, name=f"r{i}.wav", data=_wav_bytes(1.0 + 0.2 * i)).json()["job_ids"][0]
        out.append(client.get(f"/api/jobs/{job_id}", headers=headers).json()["analysis_id"])
    return out


def test_comparison_two_analyses(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        a, b = _ids(client, ctx["auth"](), 2)
        r = client.get(f"/api/comparisons?ids={a},{b}", headers=ctx["auth"]())
        assert r.status_code == 200
        body = r.json()
        assert set(body["analysis_ids"]) == {a, b} and body["config_mismatch"] is False
        paths = {row["path"]: row for row in body["rows"]}
        assert paths["pitch.f0_range_st"]["verdict"] == "unchanged"
        assert paths["transcript.derived.clarity.rushed_word_fraction"]["verdict"] == "unavailable"
        assert set(body["trend"]) == set(paths)


def test_comparison_file_names_match_analysis_ids_order(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        headers = ctx["auth"]()
        first_job = _upload(client, headers, name="r0.wav", data=_wav_bytes(1.0)).json()["job_ids"][0]
        second_job = _upload(client, headers, name="r1.wav", data=_wav_bytes(1.2)).json()["job_ids"][0]
        a = client.get(f"/api/jobs/{first_job}", headers=headers).json()["analysis_id"]
        b = client.get(f"/api/jobs/{second_job}", headers=headers).json()["analysis_id"]

        r = client.get(f"/api/comparisons?ids={a},{b}", headers=headers)

        assert r.status_code == 200
        body = r.json()
        assert body["analysis_ids"] == [a, b]
        assert body["file_names"] == ["r0.wav", "r1.wav"]


def test_comparison_validation_and_scoping(tmp_path):
    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        a, b = _ids(client, ctx["auth"]("alice"), 2)
        assert client.get(f"/api/comparisons?ids={a}", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get(f"/api/comparisons?ids={a},{a}", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get("/api/comparisons?ids=nope,also", headers=ctx["auth"]("alice")).status_code == 400
        assert client.get(f"/api/comparisons?ids={a},{uuid.uuid4()}", headers=ctx["auth"]("alice")).status_code == 404
        assert client.get(f"/api/comparisons?ids={a},{b}", headers=ctx["auth"]("bob")).status_code == 404


def test_comparison_caps_the_number_of_ids(tmp_path):
    from vocal_coach.api.comparisons import MAX_COMPARE_IDS

    app, ctx = make_test_app(tmp_path, job_fn=fake_job_fn)
    with TestClient(app) as client:
        too_many = ",".join(str(uuid.uuid4()) for _ in range(MAX_COMPARE_IDS + 1))
        r = client.get(f"/api/comparisons?ids={too_many}", headers=ctx["auth"]())
        assert r.status_code == 400 and str(MAX_COMPARE_IDS) in r.json()["detail"]
        at_cap = ",".join(str(uuid.uuid4()) for _ in range(MAX_COMPARE_IDS))
        assert client.get(f"/api/comparisons?ids={at_cap}", headers=ctx["auth"]()).status_code == 404  # allowed, unknown
