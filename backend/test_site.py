"""Verify that the Render web service serves the form without exposing backend files."""
from unittest.mock import Mock

import pytest

from backend.app import create_app


@pytest.fixture
def configured_client(monkeypatch):
    monkeypatch.setenv('ALLOWED_ORIGINS', 'https://proresolutions.onrender.com')
    return create_app(store=Mock(), clickup=Mock()).test_client()


def test_public_form_and_assets_are_served(configured_client):
    page = configured_client.get('/')
    assert page.status_code == 200
    assert page.mimetype == 'text/html'
    assert b'id="quote-form"' in page.data
    assert b'Pro Resolutions' in page.data
    for path, mime in [('/app.js', 'text/javascript'), ('/style.css', 'text/css'), ('/mark.svg', 'image/svg+xml')]:
        response = configured_client.get(path)
        assert response.status_code == 200
        assert response.mimetype == mime


@pytest.mark.parametrize('path', ['/backend/app.py', '/backend/schema.sql', '/render.yaml', '/.env', '/README.md'])
def test_server_files_are_not_public(configured_client, path):
    assert configured_client.get(path).status_code == 404


def test_same_origin_api_config_uses_browser_origin(configured_client):
    config = configured_client.get('/api-config.js')
    assert config.status_code == 200
    assert config.mimetype == 'text/javascript'
    assert b'window.location.origin' in config.data
    assert b'no-store' in config.headers['Cache-Control'].encode()


def test_missing_connections_keeps_preview_available(monkeypatch):
    for name in ['DATABASE_URL', 'CLICKUP_TOKEN', 'CLICKUP_LIST_ID']:
        monkeypatch.delenv(name, raising=False)
    client = create_app().test_client()
    assert client.get('/').status_code == 200
    assert client.get('/health').status_code == 200
    assert client.get('/ready').status_code == 503
    assert b"window.PRO_RESOLUTIONS_API = '';" in client.get('/api-config.js').data
