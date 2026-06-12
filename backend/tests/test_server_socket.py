"""backend/core/server_socket.py 단위 테스트."""

from __future__ import annotations

import http.server
import json
import logging
import socket
import sys
import threading

import pytest

from core import config as _cfg


def _free_port() -> int:
    """OS 가 할당 가능한 포트 1개를 반환한다."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def _isolate_config(monkeypatch):
    """config.PORT / ALLOWED_ORIGIN 스냅샷 복원 + 상수 0 수렴(테스트 속도)."""
    orig_port = _cfg.PORT
    orig_origin = _cfg.ALLOWED_ORIGIN
    monkeypatch.setattr("core.server_socket.SAME_APP_PROBE_TIMEOUT", 0.1)
    monkeypatch.setattr("core.server_socket.BIND_RETRY_INTERVAL", 0.0)
    yield
    _cfg.PORT = orig_port
    _cfg.ALLOWED_ORIGIN = orig_origin


# ---------------------------------------------------------------------------
# 1. dev → DEV_PORT 바인딩
# ---------------------------------------------------------------------------


def test_dev_binds_dev_port(monkeypatch):
    """dev 경로: DEV_PORT 로 바인딩된 소켓을 반환하고 config.PORT 를 갱신한다."""
    free = _free_port()
    monkeypatch.setattr("core.server_socket.DEV_PORT", free)
    monkeypatch.setattr(sys, "frozen", False, raising=False)

    from core.server_socket import create_server_socket

    sock = create_server_socket()
    try:
        assert sock.getsockname()[1] == free
        assert _cfg.PORT == free
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 2. frozen + APP_PORT 명시 → 그 포트
# ---------------------------------------------------------------------------


def test_frozen_explicit_port(monkeypatch):
    """frozen + APP_PORT 명시 → 지정 포트에 바인딩된다."""
    free = _free_port()
    monkeypatch.setenv("APP_PORT", str(free))
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    from core.server_socket import create_server_socket

    sock = create_server_socket()
    try:
        assert sock.getsockname()[1] == free
        assert _cfg.PORT == free
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 3. 해시 포트 결정론 + 회귀 핀
# ---------------------------------------------------------------------------


def test_hash_port_deterministic_and_in_range():
    """APP_NAME 해시 포트가 결정론적이고 규정 범위 내에 있다."""
    from core.server_socket import (
        FROZEN_PORT_RANGE_SIZE,
        FROZEN_PORT_RANGE_START,
        default_frozen_port,
    )

    assert default_frozen_port("SenPIA") == 47381
    assert default_frozen_port("MyAgent") == 48011

    for name in ("Alpha", "Beta", "Gamma"):
        port = default_frozen_port(name)
        assert (
            FROZEN_PORT_RANGE_START
            <= port
            < FROZEN_PORT_RANGE_START + FROZEN_PORT_RANGE_SIZE
        )


# ---------------------------------------------------------------------------
# 4. 점유 포트 → 후보 체인 폴백
# ---------------------------------------------------------------------------


def test_frozen_port_chain_fallback(monkeypatch):
    """base 포트 점유 시 chain 내 다음 후보로 폴백한다."""
    base = _free_port()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.server_socket._resolve_frozen_port_base", lambda: base)

    # bind 만 하고 listen 안 함 → 프로브가 ECONNREFUSED(refused=True)
    blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    blocker.bind(("127.0.0.1", base))

    from core.server_socket import PORT_FALLBACK_ATTEMPTS, create_server_socket

    try:
        sock = create_server_socket()
        try:
            result_port = sock.getsockname()[1]
            assert result_port != base
            assert base < result_port < base + PORT_FALLBACK_ATTEMPTS
        finally:
            sock.close()
    finally:
        blocker.close()


# ---------------------------------------------------------------------------
# 5 & 6. HTTP 프로브 — 같은 앱 vs 다른 앱
# ---------------------------------------------------------------------------


def _make_app_info_server(name: str) -> tuple[http.server.HTTPServer, int]:
    """/api/app-info 에 name 을 반환하는 임시 HTTP 서버(OS 할당 포트)를 반환한다."""

    class _Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = json.dumps({"name": name}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):  # noqa: N802
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, srv.server_address[1]


def test_same_app_probe_raises(monkeypatch):
    """점유 포트가 같은 APP_NAME 을 반환하면 ServerAlreadyRunning 을 올린다."""
    srv, port = _make_app_info_server(_cfg.APP_NAME)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.server_socket._resolve_frozen_port_base", lambda: port)

    from core.server_socket import ServerAlreadyRunning, create_server_socket

    try:
        with pytest.raises(ServerAlreadyRunning) as exc_info:
            create_server_socket()
        assert f":{port}" in exc_info.value.url
    finally:
        srv.shutdown()


def test_different_app_probe_falls_back(monkeypatch):
    """점유 포트가 다른 앱 이름을 반환하면 예외 없이 다음 후보로 폴백한다."""
    srv, port = _make_app_info_server("OtherApp")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.server_socket._resolve_frozen_port_base", lambda: port)

    from core.server_socket import create_server_socket

    try:
        sock = create_server_socket()
        try:
            assert sock.getsockname()[1] != port
        finally:
            sock.close()
    finally:
        srv.shutdown()


# ---------------------------------------------------------------------------
# 7. APP_PORT=0 → 동적 escape hatch
# ---------------------------------------------------------------------------


def test_dynamic_port_escape_hatch(monkeypatch):
    """APP_PORT=0 → 동적 포트가 배정되고 config.PORT 가 갱신된다."""
    monkeypatch.setenv("APP_PORT", "0")
    monkeypatch.setattr(sys, "frozen", True, raising=False)

    from core.server_socket import create_server_socket

    sock = create_server_socket()
    try:
        assert sock.getsockname()[1] > 0
        assert _cfg.PORT == sock.getsockname()[1]
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# 8. 후보 전수 점유 → 동적 최후수단 + warning
# ---------------------------------------------------------------------------


def test_all_candidates_occupied_dynamic_fallback(monkeypatch, caplog):
    """후보 포트 전수 점유 시 동적 포트로 폴백하고 warning 로그를 남긴다."""
    from core.server_socket import PORT_FALLBACK_ATTEMPTS, create_server_socket

    base = _free_port()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("core.server_socket._resolve_frozen_port_base", lambda: base)

    blockers: list[socket.socket] = []
    try:
        for i in range(PORT_FALLBACK_ATTEMPTS):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", base + i))
            blockers.append(s)

        with caplog.at_level(logging.WARNING, logger="core.server_socket"):
            sock = create_server_socket()
        try:
            assert sock.getsockname()[1] > 0
            assert "falling back to dynamic port" in caplog.text
        finally:
            sock.close()
    finally:
        for s in blockers:
            s.close()


# ---------------------------------------------------------------------------
# 9. APP_PORT 비정수 → 해시 기본값
# ---------------------------------------------------------------------------


def test_invalid_app_port_falls_back_to_hash(monkeypatch):
    """APP_PORT 가 비정수일 때 _resolve_frozen_port_base 가 해시 기본값을 반환한다."""
    monkeypatch.setenv("APP_PORT", "not-a-number")

    from core.server_socket import _resolve_frozen_port_base, default_frozen_port

    expected = default_frozen_port(_cfg.APP_NAME)
    assert _resolve_frozen_port_base() == expected
