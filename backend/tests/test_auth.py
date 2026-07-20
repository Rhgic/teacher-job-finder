import importlib


def load_auth(monkeypatch, secret: str = "test-secret"):
    monkeypatch.setenv("SESSION_SECRET", secret)
    import config

    importlib.reload(config)
    import services.auth as auth

    return importlib.reload(auth)


def test_token_round_trip(monkeypatch):
    auth = load_auth(monkeypatch)
    token = auth.make_token("user-123")
    assert auth.verify_token(token) == "user-123"


def test_token_tamper_fails(monkeypatch):
    auth = load_auth(monkeypatch)
    token = auth.make_token("user-123")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    assert auth.verify_token(tampered) is None
