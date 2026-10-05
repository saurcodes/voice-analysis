"""The uvicorn access-log filter that keeps the Drive OAuth callback's code and state out of the logs."""
import logging

from tests.api_fixtures import make_test_app
from vocal_coach.logging_filters import ACCESS_LOGGER, RedactDriveCallbackQuery


def _access_record(args):
    return logging.LogRecord(ACCESS_LOGGER, logging.INFO, __file__, 1, '%s - "%s %s HTTP/%s" %d', args, None)


def test_callback_query_is_redacted():
    record = _access_record(("172.18.0.5:41234", "GET", "/api/drive/callback?code=4/abc&state=xyz", "1.1", 302))
    assert RedactDriveCallbackQuery().filter(record) is True
    assert record.args == ("172.18.0.5:41234", "GET", "/api/drive/callback?[redacted]", "1.1", 302)
    assert "code=" not in record.getMessage() and "state=" not in record.getMessage()


def test_other_paths_are_untouched():
    args = ("172.18.0.5:41234", "GET", "/api/me?x=1", "1.1", 200)
    record = _access_record(args)
    assert RedactDriveCallbackQuery().filter(record) is True
    assert record.args == args


def test_non_access_shaped_args_are_untouched():
    record = logging.LogRecord(ACCESS_LOGGER, logging.INFO, __file__, 1, "%(path)s",
                               ({"path": "/api/drive/callback?code=1"},), None)
    mapping_args = record.args
    assert RedactDriveCallbackQuery().filter(record) is True
    assert record.args is mapping_args

    short = _access_record(("/api/drive/callback?code=1",))
    assert RedactDriveCallbackQuery().filter(short) is True
    assert short.args == ("/api/drive/callback?code=1",)


def test_create_app_installs_the_filter_exactly_once(tmp_path):
    for name in ("one", "two"):
        (tmp_path / name).mkdir()
        make_test_app(tmp_path / name)
    installed = [f for f in logging.getLogger(ACCESS_LOGGER).filters if isinstance(f, RedactDriveCallbackQuery)]
    assert len(installed) == 1
