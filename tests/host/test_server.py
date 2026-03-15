from host.server import create_app


def test_healthz_returns_ok() -> None:
    app = create_app()
    client = app.test_client()

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True}


def test_button_press_requires_auth_when_configured(monkeypatch) -> None:
    monkeypatch.setenv("OSU_HOST_TOKEN", "token-1")
    app = create_app()
    client = app.test_client()

    response = client.post("/button/press")

    assert response.status_code == 401
