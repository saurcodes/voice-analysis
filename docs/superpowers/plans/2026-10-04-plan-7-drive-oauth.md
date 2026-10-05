# Vocal Coach — Plan 7: Per-user Google Drive OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Backend tasks run with `backend/.venv/bin/python`; frontend tasks from `frontend/` with npm. Frontend implementers invoke the `design-taste-frontend` skill before UI code.

**Goal:** Let each signed-in user link their own Google Drive, browse audio/video files there, and analyse them without uploading, with refresh tokens stored encrypted and never exposed.

**Architecture:** A `vocal_coach/drive/` package over `httpx` (no Google SDK): `state.py` signs the OAuth `state` with itsdangerous; `crypto.py` wraps Fernet for refresh tokens; `oauth.py` builds the consent URL and exchanges/refreshes/revokes tokens; `client.py` lists and downloads Drive files; `cache.py` names per-user cached downloads by file id + modifiedTime; `service.py` is the single entry point used by the API and the pipeline (connection lookup, per-request access token, revoked-token handling). Four API routes under `/api/drive`, `/me.drive_connected`, and a JSON branch on `POST /api/analyses` that creates one job per Drive file; the pipeline's existing `download` stage fetches into the cache inside the worker. The frontend gets a Settings connect/disconnect block and a Drive browser tab in the Analyse drawer.

**Tech Stack:** Python 3.12, httpx (sync, already a dependency), `itsdangerous>=2.2` (new), `cryptography` Fernet (already installed transitively; add an explicit `cryptography>=42` dependency), FastAPI, SQLAlchemy; `pytest-httpx` for Google endpoint mocks; React/TanStack Query for the UI.

**Spec:** `docs/superpowers/specs/2026-10-03-vocal-coach-design.md` §5 (Input: Google Drive), §8 (`drive_connections`), §12 (API rows `/me`, `/drive/*`, `POST /analyses` JSON), §13 (Settings, Drive browser), §14 (`.env.example` keys), §15 (409 `drive_not_connected`, revoked token), §16 (`test_drive_oauth`, `test_drive_cache`).

**Spec amendments made by this plan:**
1. §5 scope: `https://www.googleapis.com/auth/drive.readonly` plus `https://www.googleapis.com/auth/userinfo.email`, so `google_email` can be stored and shown in Settings (the spec's table already has the column).
2. §12 `/me` gains `drive_configured: bool` (server has `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`); when false, `/drive/connect` and `/drive/files` return 503 `{"detail": "drive is not configured on this server"}` and the UI shows that text instead of a Connect button.
3. §5 cache: the Drive download is cached as the original file; the derived 16 kHz WAV is NOT kept beside it (the pipeline already derives it per job in a temp work dir and deletes it). Cache hit = no download.
4. §12 `POST /analyses` JSON body is `{"source": "drive", "file_ids": [...], "speaker_context": str | null, "llm": {"enabled": bool, "model": str | null}}`, 1 to 20 ids; response `{job_ids: [...]}` in the same order; a file id the user cannot read (404 at Google) → 404 `{"detail": "drive file <id> not found"}` and no jobs are created.

## Global Constraints

- Refresh tokens are stored only Fernet-encrypted (`DRIVE_TOKEN_KEY`, a Fernet key); access tokens are obtained per request from the refresh token and never stored, logged, or returned by any endpoint. No token or client secret ever appears in a log line, an error detail, or a job error message.
- OAuth `state` = itsdangerous `URLSafeTimedSerializer(SECRET_KEY, salt="drive-oauth")` payload `{"user_id": str, "nonce": str}` with `max_age=600` seconds on verification; a tampered or expired state → 400 `{"detail": "invalid or expired state"}` (never a redirect to the frontend with a success flag).
- Google token endpoint `https://oauth2.googleapis.com/token`, revoke `https://oauth2.googleapis.com/revoke`, userinfo `https://www.googleapis.com/oauth2/v3/userinfo`, Drive v3 `https://www.googleapis.com/drive/v3/files` (list and `?alt=media` download). Consent URL `https://accounts.google.com/o/oauth2/v2/auth` with `access_type=offline`, `prompt=consent`, `include_granted_scopes=true`.
- Allowed extensions `{m4a, mp3, wav, mov, mp4}` (reuse `ALLOWED_EXTENSIONS` from `api/analyses.py`; move it to a shared module if importing it creates a cycle).
- Cache layout `DATA_DIR/cache/<user_id>/<file_id>__<modifiedTime-sanitised>.<ext>` where sanitised = `modifiedTime` with every character outside `[A-Za-z0-9._-]` replaced by `-`.
- Drive not connected → 409 `{"detail": "drive_not_connected"}` (exact string). Google refresh failing with `invalid_grant` (revoked) → delete the connection row, then 409 `drive_not_connected`. Other Google errors → 502 `{"detail": "google drive error <status>"}`.
- Strict per-user scoping: connection rows, cache directories and jobs are keyed by `user_id`; another user's connection is never readable.
- All tests offline: Google endpoints mocked with `pytest-httpx`; `-W error` stays clean; existing 387 backend and 130 frontend tests stay green.
- Zero em-dashes (U+2014) and no ellipsis character (U+2026) in anything written. Commits end with `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Review Focus

1. **User revokes access in their Google account, then opens the Drive tab:** the refresh fails with `invalid_grant`; the row is deleted, `/drive/files` returns 409, `/me.drive_connected` flips to false, the UI shows the connect prompt, nothing crashes. Test in Task 3.
2. **Two jobs for the same Drive file submitted together, or a re-analysis after the file changed in Drive:** cache key includes `modifiedTime`, so the changed file downloads again; two concurrent jobs for the same key must not corrupt the cache (download to a temp path, then atomic rename; a second job finds the file). Test in Task 4.
3. **Callback hit twice (browser refresh) or by a different signed-in user than the one who started:** the state binds `user_id`; the callback stores the connection for the state's user only and does not require the Keycloak bearer (the browser arrives via redirect); a replayed `code` fails at Google → 303 to `/settings?drive=error` (a bad or missing state stays 400 `invalid or expired state`), no stack trace. Test in Task 3.
4. **Drive listing with pagination and non-media files:** folders, Google Docs and PDFs are filtered out; `nextPageToken` pages are followed up to 1000 files; an empty folder yields `[]`; an invalid `folder_id` → 404 `{"detail": "folder not found"}`. Test in Task 2.
5. **Server without Google credentials (default `.env`):** `/me.drive_configured` false; connect/files return 503 with the documented detail; Settings and the Drive tab show "Google Drive is not configured on this server" and nothing else breaks. Test in Tasks 3 and 5.

---

### Task 1: Settings, token crypto, signed state, connection repository

**Files:**
- Modify: `backend/vocal_coach/settings.py` (add `secret_key: str = "dev-secret-change-me"`, `drive_token_key: str | None = None`, `google_client_id: str | None = None`, `google_client_secret: str | None = None`, `google_redirect_uri: str = "http://localhost:8000/api/drive/callback"`, property `drive_configured -> bool` = all of client id, client secret, token key set)
- Modify: `backend/pyproject.toml` (deps `itsdangerous>=2.2`, `cryptography>=42`), regenerate `backend/requirements.lock` with `.venv/bin/pip freeze --exclude-editable`
- Create: `backend/vocal_coach/drive/__init__.py`, `backend/vocal_coach/drive/crypto.py`, `backend/vocal_coach/drive/state.py`, `backend/vocal_coach/drive/errors.py`
- Modify: `backend/vocal_coach/storage/repo.py` (add `get_drive_connection(session, user_id) -> DriveConnection | None`, `upsert_drive_connection(session, user_id, *, encrypted_refresh_token: bytes, google_email: str | None) -> DriveConnection`, `delete_drive_connection(session, user_id) -> bool`)
- Test: `backend/tests/test_drive_oauth.py` (state + crypto parts), extend `backend/tests/test_repo.py`, `backend/tests/test_settings.py`

**Interfaces (Produces):**

```python
# drive/errors.py
class DriveError(RuntimeError): """Google returned an unexpected error; message carries only a status code."""
class DriveNotConnected(DriveError): """No usable connection for this user (never linked, or token revoked)."""
class DriveNotConfigured(DriveError): """Server lacks Google credentials."""
class DriveNotFound(DriveError): """File or folder not found / not readable."""

# drive/crypto.py
def encrypt_token(key: str, token: str) -> bytes      # Fernet(key.encode()).encrypt(token.encode())
def decrypt_token(key: str, blob: bytes) -> str       # InvalidToken → DriveError("stored token cannot be decrypted")
def generate_key() -> str                             # Fernet.generate_key().decode(), for the README

# drive/state.py
STATE_MAX_AGE_S = 600
def sign_state(secret_key: str, user_id: uuid.UUID) -> str          # payload {"user_id": str(user_id), "nonce": secrets.token_urlsafe(16)}
def verify_state(secret_key: str, state: str) -> uuid.UUID          # BadSignature/SignatureExpired → DriveError("invalid or expired state")
```

- [ ] **Step 1: Failing tests**

```python
# tests/test_drive_oauth.py (part 1)
import uuid, pytest
from vocal_coach.drive import crypto, state
from vocal_coach.drive.errors import DriveError

def test_state_round_trip_and_tamper():
    uid = uuid.uuid4()
    s = state.sign_state("k", uid)
    assert state.verify_state("k", s) == uid
    with pytest.raises(DriveError, match="invalid or expired state"):
        state.verify_state("k", s[:-2] + "xx")
    with pytest.raises(DriveError):
        state.verify_state("other-key", s)

def test_state_expired(monkeypatch):
    import itsdangerous
    uid = uuid.uuid4()
    s = state.sign_state("k", uid)
    real = itsdangerous.URLSafeTimedSerializer.loads
    def expired(self, value, max_age=None, **kw):
        raise itsdangerous.SignatureExpired("old")
    monkeypatch.setattr(itsdangerous.URLSafeTimedSerializer, "loads", expired)
    with pytest.raises(DriveError, match="invalid or expired state"):
        state.verify_state("k", s)

def test_token_encrypt_decrypt_round_trip():
    key = crypto.generate_key()
    blob = crypto.encrypt_token(key, "1//refresh")
    assert blob != b"1//refresh" and crypto.decrypt_token(key, blob) == "1//refresh"
    with pytest.raises(DriveError):
        crypto.decrypt_token(crypto.generate_key(), blob)
```

`test_repo.py`: upsert then get returns the row with the same bytes and email; upsert again replaces the token; delete returns True then False; another user's `get_drive_connection` is None. `test_settings.py`: `drive_configured` false by default, true when the three values are set.

- [ ] **Step 2: Implement; `.venv/bin/pip install -e ".[dev]"`; regenerate the lock (pins for parselmouth/numpy/scipy unchanged); run the three test files and the full suite `-W error`; commit**

```bash
git add backend/pyproject.toml backend/requirements.lock backend/vocal_coach/settings.py backend/vocal_coach/drive backend/vocal_coach/storage/repo.py backend/tests/test_drive_oauth.py backend/tests/test_repo.py backend/tests/test_settings.py
git commit -m "feat(drive): settings, Fernet token crypto, signed OAuth state, connection repository

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 2: Drive HTTP client and download cache

**Files:**
- Create: `backend/vocal_coach/drive/client.py`, `backend/vocal_coach/drive/cache.py`
- Modify: `backend/vocal_coach/storage/paths.py` (add `CACHE_SUBDIR = "cache"`, `cache_dir(data_dir, user_id)`) or keep cache naming in `drive/cache.py` and import `paths` for the base; choose one and say which
- Test: `backend/tests/test_drive_client.py`, `backend/tests/test_drive_cache.py`

**Interfaces (Produces):**

```python
# drive/client.py
DRIVE_API = "https://www.googleapis.com/drive/v3/files"
PAGE_SIZE = 200
MAX_FILES = 1000
MEDIA_EXTENSIONS = {"m4a", "mp3", "wav", "mov", "mp4"}

@dataclass(frozen=True)
class DriveFile:
    id: str; name: str; mime_type: str; modified_time: str; size: int | None
    @property
    def ext(self) -> str   # lowercase extension without dot, "" when none

class DriveClient:
    def __init__(self, access_token: str, *, timeout: httpx.Timeout | float = httpx.Timeout(10.0, read=60.0)) -> None
    def list_media(self, folder_id: str | None) -> list[DriveFile]
        # GET DRIVE_API with params q="'<folder or root>' in parents and trashed = false",
        # fields="nextPageToken,files(id,name,mimeType,modifiedTime,size)", pageSize=PAGE_SIZE, follows nextPageToken until MAX_FILES;
        # keeps files whose ext in MEDIA_EXTENSIONS and mime_type != "application/vnd.google-apps.folder"; sorted by name
        # 401 → DriveNotConnected; 404 → DriveNotFound("folder not found"); other non-2xx → DriveError(f"google drive error {status}"); transport → DriveError("google drive connection error")
    def get_file(self, file_id: str) -> DriveFile        # GET DRIVE_API/{id}?fields=id,name,mimeType,modifiedTime,size; 404 → DriveNotFound(f"drive file {file_id} not found")
    def download(self, file_id: str, dest: Path) -> Path  # GET DRIVE_API/{id}?alt=media streamed to dest.with_suffix(dest.suffix + ".part") then os.replace → dest

# drive/cache.py
def sanitise(value: str) -> str                      # re.sub(r"[^A-Za-z0-9._-]", "-", value)
def cache_path(data_dir: Path, user_id: uuid.UUID, file: DriveFile) -> Path   # data_dir/cache/<user_id>/<id>__<sanitise(modified_time)>.<ext>
def ensure_cached(data_dir: Path, user_id: uuid.UUID, file: DriveFile, client: DriveClient) -> tuple[Path, bool]
        # returns (path, downloaded); no download when the path exists and size > 0
```

- [ ] **Step 1: Failing tests** (`pytest-httpx` `httpx_mock`): listing filters folders/docs and keeps media sorted; follows `nextPageToken` across two pages; empty → `[]`; 401 → `DriveNotConnected`; 404 → `DriveNotFound`; `get_file` 404 message; `download` writes bytes atomically (no `.part` left) and streams (mock a 3-chunk body); cache: key sanitises `2026-10-04T10:42:00.000Z` → `2026-10-04T10-42-00.000Z`, per-user directory, hit returns `downloaded False` without a request (assert no HTTP call), miss downloads once, a zero-byte stale file counts as a miss.

- [ ] **Step 2: Implement, run, commit**

```bash
git add backend/vocal_coach/drive backend/vocal_coach/storage/paths.py backend/tests/test_drive_client.py backend/tests/test_drive_cache.py
git commit -m "feat(drive): httpx Drive client with paging and media filter; per-user download cache

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 3: OAuth flow service and `/api/drive` routes, `/me`

**Files:**
- Create: `backend/vocal_coach/drive/oauth.py`, `backend/vocal_coach/drive/service.py`, `backend/vocal_coach/api/drive.py`
- Modify: `backend/vocal_coach/main.py` (include the router), `backend/vocal_coach/api/me.py` (`drive_connected`, `drive_configured`), `backend/tests/api_fixtures.py` (`make_test_app(..., settings_overrides: dict | None = None)` merged into the `Settings(...)` call so tests can set the Google keys)
- Test: extend `backend/tests/test_drive_oauth.py` (part 2), `backend/tests/test_api_drive.py`

**Interfaces (Produces):**

```python
# drive/oauth.py
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"; TOKEN_URL = "https://oauth2.googleapis.com/token"; REVOKE_URL = "https://oauth2.googleapis.com/revoke"; USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
SCOPES = ("https://www.googleapis.com/auth/drive.readonly", "https://www.googleapis.com/auth/userinfo.email")
def consent_url(settings: Settings, state: str) -> str          # urlencode client_id, redirect_uri, response_type=code, scope=" ".join(SCOPES), access_type=offline, prompt=consent, include_granted_scopes=true, state
@dataclass
class TokenExchange: refresh_token: str; access_token: str; email: str | None
def exchange_code(settings: Settings, code: str) -> TokenExchange   # POST TOKEN_URL form grant_type=authorization_code; missing refresh_token → DriveError("google did not return a refresh token"); then GET USERINFO_URL with bearer → email (failure → None)
def refresh_access_token(settings: Settings, refresh_token: str) -> str   # POST TOKEN_URL grant_type=refresh_token; 400 with error == "invalid_grant" → DriveNotConnected; other non-2xx → DriveError(f"google token error {status}")
def revoke(token: str) -> None                                    # POST REVOKE_URL token=...; ignore failures (log at INFO)

# drive/service.py  (API and pipeline only touch this module)
def require_configured(settings) -> None                          # DriveNotConfigured
def start_connect(settings, user_id) -> str                        # require_configured; consent_url(settings, sign_state(settings.secret_key, user_id))
def complete_connect(session, settings, *, code: str, state: str) -> uuid.UUID
        # user_id = verify_state; exchange_code; upsert_drive_connection(encrypt_token(drive_token_key, refresh_token), email); returns user_id
def disconnect(session, settings, user_id) -> bool                 # row → decrypt → revoke (best effort) → delete; False when no row
def access_token_for(session, settings, user_id) -> str            # row or DriveNotConnected; refresh; on DriveNotConnected from refresh → delete row then re-raise
def list_files(session, settings, user_id, folder_id: str | None) -> list[DriveFile]
def connection_status(session, user_id) -> tuple[bool, str | None]  # (connected, google_email)
```

API (`api/drive.py`, prefix `/drive`):
- `GET /drive/connect` (auth) → `{"url": str}`; `DriveNotConfigured` → 503.
- `GET /drive/callback?code&state` (NO bearer; the browser arrives by redirect) → on success `RedirectResponse(f"{settings.frontend_origin}/settings?drive=connected", 303)`; `DriveError` from state → 400 `{"detail": "invalid or expired state"}`; Google error → 502; Google `error=access_denied` query param (user cancelled) → redirect to `/settings?drive=cancelled`.
- `DELETE /drive/connect` (auth) → 204; 404 when not connected.
- `GET /drive/files?folder_id=` (auth) → `list[DriveFileOut {id, name, mime_type, modified_time, size}]`; `DriveNotConnected` → 409 `drive_not_connected`; `DriveNotFound` → 404 `folder not found`; `DriveNotConfigured` → 503; `DriveError` → 502. Google calls run in `asyncio.to_thread`.
- `GET /me` → `drive_connected`, `drive_configured`. Document all `responses` for OpenAPI.

Error mapping lives in one helper `drive_http_error(e: DriveError) -> HTTPException` used by every route.

- [ ] **Step 1: Failing tests**

`test_drive_oauth.py` part 2 (pytest-httpx): `exchange_code` posts the form and returns tokens + email; missing refresh token → `DriveError`; `refresh_access_token` `invalid_grant` → `DriveNotConnected`; `consent_url` contains `access_type=offline`, `prompt=consent`, both scopes, the state.

`test_api_drive.py` (with `settings_overrides` providing `google_client_id="cid"`, `google_client_secret="sec"`, `drive_token_key=crypto.generate_key()`, `secret_key="s"`): connect returns a Google URL whose `state` verifies to the caller's user id; callback with a valid state and mocked Google stores a connection (row exists, `google_email` set, `encrypted_refresh_token` decrypts to the mocked refresh token) and redirects 303 to `/settings?drive=connected`; callback with a tampered state → 400; callback replay (Google token endpoint returns 400 `invalid_grant`) → 502 with the plain detail; callback `error=access_denied` → redirect `/settings?drive=cancelled`; `/me` shows `drive_connected` true after connect; `/drive/files` lists mocked media; `/drive/files` when the refresh returns `invalid_grant` → 409 `drive_not_connected` AND the row is gone AND `/me.drive_connected` false (Review Focus 1); `DELETE` revokes (assert the revoke request happened) and 204, then 404; unconfigured app (no overrides) → `/me.drive_configured` false, connect and files 503 (Review Focus 5); another user cannot see the connection (their `/drive/files` → 409).

- [ ] **Step 2: Implement, run, re-export OpenAPI (`cd backend && .venv/bin/python scripts/export_openapi.py`), commit**

```bash
git add backend/vocal_coach backend/tests backend/openapi.json
git commit -m "feat(drive): OAuth connect/callback/disconnect, file listing, /me drive status

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 4: Drive-sourced analyses: JSON branch and pipeline download stage

**Files:**
- Modify: `backend/vocal_coach/api/analyses.py` (JSON branch), `backend/vocal_coach/pipeline.py` (download stage), `backend/vocal_coach/drive/service.py` (add `download_for_job`), `backend/vocal_coach/storage/repo.py` only if a helper is needed
- Test: `backend/tests/test_api_analyses.py` (new JSON cases), `backend/tests/test_pipeline.py` (download stage), `backend/tests/test_drive_cache.py` (concurrency)

**Behaviour:**
- Request model `DriveAnalysisRequest { source: Literal["drive"], file_ids: list[str] = Field(min_length=1, max_length=20), speaker_context: str | None = Field(default=None, max_length=SPEAKER_CONTEXT_MAX_CHARS), llm: LlmOptions = LlmOptions() }` with `LlmOptions { enabled: bool = False, model: str | None = None }`. Replace the 501 branch: parse the body with this model (422 on validation); `token = service.access_token_for(...)` (409/503 mapping via `drive_http_error`); for each id `client.get_file` (404 aborts the whole request before any job is created); then for each file: `recorded_at = modified_time` parsed as aware datetime; `path = cache.cache_path(data_dir, user.id, file)`; `job = repo.create_job(session, user.id, file_name=file.name, source_sha256=None, recorded_at=recorded_at)`; `JobRequest(job_id, user_id, source_path=path, file_name=file.name, recorded_at, drive_file_id=file.id, drive_modified_time=file.modified_time, speaker_context, llm_enabled, llm_model, source_sha256=None)`; `submit_or_503` each; return the ids in order. Update `UPLOAD_OPENAPI` so the JSON body schema is declared (`application/json` with `DriveAnalysisRequest`) and the 501 response is replaced by 409 and 404 entries.
- `drive/service.py`: `download_for_job(session, settings, user_id, file_id, modified_time, dest: Path) -> Path`: if `dest` exists and is non-empty return it; else `token = access_token_for(...)`, `DriveClient(token).download(file_id, dest)`; errors propagate as `DriveError` subclasses.
- Pipeline download stage: when `req.drive_file_id` is set and `req.source_path` does not exist (or is empty), call `drive_service.download_for_job(session, settings, req.user_id, req.drive_file_id, req.drive_modified_time or "", req.source_path)`; `DriveNotConnected` → `RuntimeError("Google Drive is no longer connected; reconnect it in Settings and retry")`; `DriveNotFound` → `RuntimeError(f"Drive file {req.file_name} was not found")`; `DriveError` → `RuntimeError("could not download from Google Drive")`. These become the job's user-facing error (never a token or URL). `progress("download", 5)` emitted before the download as today.
- Cache concurrency: `DriveClient.download` writes `dest + ".part"` with a unique suffix (`f".{os.getpid()}.part"`) then `os.replace`; `ensure_cached`/`download_for_job` re-check existence after acquiring nothing (last writer wins with identical bytes). Test two sequential downloads of the same key racing via a fake client that asserts only one real download happens when the file already exists after the first.
- Deleting an analysis with `drive_file_id` leaves the cache file (cache is bounded by Plan 8's cleanup; document).

- [ ] **Step 1: Failing tests**: JSON POST with two ids creates two jobs with `file_name`/`recorded_at` from Drive metadata, `job_ids` in order, `drive_file_id` set on the resulting `JobRequest` (capture via `job_fn`); a 404 id aborts with 404 and zero jobs; not connected → 409; `file_ids` of 21 → 422; pipeline test (ffmpeg-gated) with `drive_file_id` set and a fake `download_for_job` monkeypatched to copy a synth WAV into `source_path` → stages unchanged and analysis stored with `drive_file_id`; `DriveNotConnected` from the downloader → job error text contains "reconnect it in Settings"; cache hit skips the downloader.

- [ ] **Step 2: Implement, run, re-export OpenAPI, commit**

```bash
git add backend/vocal_coach backend/tests backend/openapi.json
git commit -m "feat(drive): Drive-sourced analyses via JSON POST and cached worker downloads

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 5: Frontend: Settings connect/disconnect and the Drive browser tab

**Files:**
- Modify: `frontend/src/api/types.ts` (via `npm run gen:api`), `frontend/src/api/hooks.ts` (`useDriveConnectUrl()` mutation GET `/api/drive/connect` → `{url}`; `useDisconnectDrive()` DELETE; `useDriveFiles(folderId, {enabled})` GET `/api/drive/files?folder_id=`; `useCreateDriveAnalyses()` POST JSON → `JobIds`), `frontend/src/pages/SettingsPage.tsx`, `frontend/src/components/library/AnalyseDrawer.tsx`
- Create: `frontend/src/components/library/DriveBrowser.tsx`
- Modify tests: `frontend/src/pages/SettingsPage.test.tsx`, `frontend/src/components/library/AnalyseDrawer.test.tsx`; create `frontend/src/components/library/DriveBrowser.test.tsx`; extend `frontend/src/test/{handlers.ts,fixtures.ts}` (`driveFile()` fixture, handlers for the four routes, `me` variants `drive_configured`/`drive_connected`)

**Behaviour:**
- Settings Drive section: `drive_configured` false → text "Google Drive is not configured on this server" and no button; configured and not connected → "Connect Google Drive" button: calls the connect mutation and `window.location.assign(url)`; connected → shows "Connected as {google_email}" (email from `/me`: add `google_email: str | null` to `/me` in Task 3 if not already; yes: Task 3 adds it) with a "Disconnect" button (secondary; confirm Dialog "Disconnect Google Drive? Analyses already made stay."); after the callback redirect `?drive=connected` show a one-line success note "Google Drive connected" and `?drive=cancelled` → "Connection cancelled"; strip the param after showing.
- `DriveBrowser` (inside the drawer's Drive tab, now enabled): folder id `Input` (placeholder "root", default root) with a "Browse" button; list from `useDriveFiles`; rows: checkbox, name, modified date (`formatDateTime`), size in KB/MB (`.num`); multi-select; states: loading skeleton rows, empty "No audio or video files in this folder", 409 → prompt "Connect Google Drive in Settings" with a link, 503 → "Google Drive is not configured on this server", 404 → "Folder not found". Selected files appear in the drawer's file summary; submit sends `POST /api/analyses` JSON `{source: "drive", file_ids, speaker_context, llm: {enabled, model}}` and feeds the returned job ids into the existing `JobProgressList` (rows named by the Drive file names). The Upload and Drive tabs are mutually exclusive sources per submit (switching tabs keeps each tab's selection).
- Drive tab trigger: enabled when `me.drive_configured`; when not configured keep it disabled with the note "Google Drive is not configured on this server" (replacing the "later release" text).
- Visual contract: design skill rules (brand `primary`, `.num` on numbers only, status colours with icon + text, Phosphor `GoogleDriveLogo`, `FolderOpen`, `CheckCircle`, no em-dashes).

- [ ] **Step 1: Failing tests**: Settings: not configured text; connect button triggers the GET and `window.location.assign` (spy); connected state shows the email and Disconnect → confirm → DELETE called → state flips; `?drive=connected` note. DriveBrowser: lists fixture files with sizes, selecting two enables submit; 409 shows the connect prompt with a link to `/settings`; 404 shows "Folder not found"; drawer submit with two Drive files posts the JSON body (assert via MSW request body) and renders two progress rows named after the files.

- [ ] **Step 2: Implement (invoke the design skill first), `npm test`/`build`/`lint` green, commit**

```bash
git add frontend
git commit -m "feat(frontend): Google Drive connect in Settings and Drive browser in the Analyse drawer

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

### Task 6: Compose, env, README

**Files:**
- Modify: `docker-compose.yml` (backend env: `SECRET_KEY`, `DRIVE_TOKEN_KEY`, `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` with default `http://localhost:3000/api/drive/callback` so the browser round trip stays on the frontend origin through the nginx proxy; `${VAR:-}` for secrets), `.env.example` (document each; `SECRET_KEY` and `DRIVE_TOKEN_KEY` generation commands), `backend/README.md` ("Google Drive" section: creating the OAuth web client in Google Cloud Console, authorised redirect URI, scopes, env keys, `python -c "from vocal_coach.drive.crypto import generate_key; print(generate_key())"`, how tokens are stored, the 409/503 semantics, cache location), `frontend/README.md` (one paragraph), `scripts/smoke.sh` (print `/me` drive flags)
- Test: compose config validates (`docker compose config -q`); controller does the browser pass.

- [ ] **Step 1: Files; `docker compose -p plan-4-api config -q`; commit**

```bash
git add docker-compose.yml .env.example backend/README.md frontend/README.md scripts/smoke.sh
git commit -m "docs(drive): compose env, .env.example keys, Google OAuth setup guide

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```

---

## Self-review notes

- **Spec coverage §5:** linking separate from login, server-wide client, offline consent (T3); connect/callback/disconnect with signed state and Fernet storage (T1, T3); listing filtered by extension with default root (T2, T3); cache key id + modifiedTime per user, hit = no download (T2, T4); upload path unchanged. §8 `drive_connections` already in models and migration; repo functions (T1). §12 rows (T3, T4); `/me` (T3). §13 Settings and Drive browser (T5). §14 env keys (T6). §15 409 `drive_not_connected` and revoked handling (T3). §16 `test_drive_oauth`, `test_drive_cache` (T1, T2, T3).
- **Amendments:** scope adds `userinfo.email`; `/me.drive_configured` + `google_email`; cache keeps only the original file; JSON body shape and 404 abort; compose redirect default on :3000.
- **Type consistency:** `DriveFile` (T2) used by `cache_path`/`ensure_cached` (T2), `service.list_files` (T3), the JSON branch (T4); `DriveError` hierarchy (T1) mapped by `drive_http_error` (T3) and the pipeline (T4); `access_token_for` (T3) used by `download_for_job` (T4); `make_test_app(settings_overrides=)` (T3) used by T4 tests.
- **Review Focus pins:** 1 → `test_api_drive.py` revoked-token case (T3); 2 → cache concurrency + modifiedTime key (T2, T4); 3 → callback tamper/replay/other-user (T3); 4 → paging/filter/404 (T2); 5 → unconfigured 503 and UI text (T3, T5).
- **Known limits:** no Google credentials on this machine, so the final review verifies with mocks and a browser pass of the not-configured and not-connected states; a real OAuth round trip needs the user's Google Cloud client (documented in T6).
