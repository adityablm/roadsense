"""Tests for the Gemini retry/fallback logic, using a fake client (no internet needed)."""
import pytest
from google.genai import errors

from app import config, llm


class FakeResponse:
    def __init__(self, text):
        self.text = text


class FakeClient:
    """Pretends to be Gemini. `script` maps model name -> list of results to give, in order."""
    def __init__(self, script):
        self.script = script
        self.calls = []
        self.models = self

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        result = self.script[model].pop(0)
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


def busy():
    return errors.ServerError(503, {"error": {"code": 503, "message": "busy", "status": "UNAVAILABLE"}})


def bad_key():
    return errors.ClientError(400, {"error": {"code": 400, "message": "API key not valid", "status": "INVALID_ARGUMENT"}})


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.setattr(config, "GEMINI_MODEL", "main-model")
    monkeypatch.setattr(config, "GEMINI_FALLBACK_MODELS", ["backup-1", "backup-2"])

    def install(script):
        fake = FakeClient(script)
        monkeypatch.setattr(llm, "_get_client", lambda: fake)
        return fake
    return install


def test_busy_main_model_falls_back(setup):
    fake = setup({"main-model": [busy(), busy()], "backup-1": ["Letter text"]})
    text, model = llm.generate("hi", wait_seconds=0)
    assert (text, model) == ("Letter text", "backup-1")
    assert fake.calls == ["main-model", "main-model", "backup-1"]   # retried once, then moved on


def test_retry_on_same_model_can_succeed(setup):
    fake = setup({"main-model": [busy(), "OK on second try"]})
    assert llm.generate("hi", wait_seconds=0) == ("OK on second try", "main-model")
    assert fake.calls == ["main-model", "main-model"]


def test_bad_key_is_not_retried(setup):
    fake = setup({"main-model": [bad_key()]})
    with pytest.raises(errors.ClientError):
        llm.generate("hi", wait_seconds=0)
    assert fake.calls == ["main-model"]


def test_everything_busy_gives_clear_message(setup):
    setup({m: [busy(), busy()] for m in ("main-model", "backup-1", "backup-2")})
    with pytest.raises(RuntimeError, match="busy"):
        llm.generate("hi", wait_seconds=0)
