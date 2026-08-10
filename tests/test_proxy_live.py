"""Проверка прокси на настоящем сокете.

Остальные тесты подменяют сетевой слой и потому не отвечают на главный
вопрос: пойдёт ли запрос через прокси на самом деле. Здесь поднимается
работающий http-прокси и обычный сервер за ним, и трафик идёт по-настоящему.
"""

from __future__ import annotations

import http.server
import socket
import threading
from typing import ClassVar
from urllib.parse import urlsplit

import pytest
import requests

from elevenlabs_voiceover.api_client import (
    ElevenLabsClient,
    apply_proxy,
    detect_proxy_scheme,
)
from elevenlabs_voiceover.config import normalize_proxy_url


class TargetHandler(http.server.BaseHTTPRequestHandler):
    """Сервер, изображающий API: отвечает JSON на любой путь."""

    def do_GET(self):
        # Список, а не объект: именно так отвечает /v1/models у ElevenLabs.
        body = b'[{"model_id": "eleven_flash_v2_5", "can_do_text_to_speech": true}]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class ProxyHandler(http.server.BaseHTTPRequestHandler):
    """Простейший http-прокси: принимает запрос в абсолютной форме и передаёт дальше."""

    seen: ClassVar[list] = []

    def do_GET(self):
        ProxyHandler.seen.append(self.path)
        parts = urlsplit(self.path)
        if not parts.hostname:
            self.send_error(400, "нужен абсолютный адрес")
            return

        upstream = socket.create_connection((parts.hostname, parts.port or 80), timeout=5)
        try:
            path = parts.path or "/"
            request = f"GET {path} HTTP/1.0\r\nHost: {parts.netloc}\r\nConnection: close\r\n\r\n"
            upstream.sendall(request.encode())

            chunks = []
            while True:
                chunk = upstream.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            upstream.close()

        self.wfile.write(b"".join(chunks))

    def log_message(self, *args):
        pass


def serve(handler) -> tuple:
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, server.server_address[1]


@pytest.fixture
def target():
    server, port = serve(TargetHandler)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def proxy():
    ProxyHandler.seen = []
    server, port = serve(ProxyHandler)
    try:
        yield f"127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


# ----------------------------------------------------------------------
def test_request_really_goes_through_proxy(target, proxy):
    session = requests.Session()
    apply_proxy(session, normalize_proxy_url(proxy))

    result = session.get(f"{target}/v1/models", timeout=5)

    assert result.status_code == 200
    assert result.json()[0]["model_id"] == "eleven_flash_v2_5"
    # Прокси должен был увидеть адрес целиком — значит запрос шёл через него.
    assert ProxyHandler.seen and ProxyHandler.seen[0].endswith("/v1/models")
    session.close()


def test_detection_finds_working_http_scheme(target, proxy):
    assert detect_proxy_scheme(proxy, timeout=5, base_url=target) == "http"


def test_detection_gives_up_on_dead_proxy(target):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        dead_port = probe.getsockname()[1]

    assert detect_proxy_scheme(f"127.0.0.1:{dead_port}", timeout=2, base_url=target) is None


def test_client_session_carries_proxy(target, proxy):
    client = ElevenLabsClient(
        "sk_test_key_1234567890",
        base_url=target,
        proxy_url=normalize_proxy_url(proxy),
    )
    try:
        models = client.list_models()
    finally:
        client.close()

    assert [m.model_id for m in models] == ["eleven_flash_v2_5"]
    assert ProxyHandler.seen


def test_seller_format_reaches_the_proxy(target, proxy):
    """Адрес в виде адрес:порт:логин:пароль должен доводить запрос до прокси."""
    host, _, port = proxy.partition(":")
    session = requests.Session()
    apply_proxy(session, normalize_proxy_url(f"{host}:{port}:wVgThP:kjSdfL"))

    result = session.get(f"{target}/v1/models", timeout=5)

    assert result.status_code == 200
    assert ProxyHandler.seen
    session.close()


def test_password_with_special_characters_works(target, proxy):
    """В паролях к прокси регулярно встречаются @ и :, адрес не должен рваться."""
    host, _, port = proxy.partition(":")
    session = requests.Session()
    apply_proxy(session, normalize_proxy_url(f"{host}:{port}:user:p@ss:word/1"))

    result = session.get(f"{target}/v1/models", timeout=5)

    assert result.status_code == 200
    assert ProxyHandler.seen
    session.close()


def test_direct_request_does_not_touch_proxy(target, proxy):
    session = requests.Session()
    apply_proxy(session, "", ignore_system_proxy=True)

    session.get(f"{target}/v1/models", timeout=5)

    assert ProxyHandler.seen == []
    session.close()
