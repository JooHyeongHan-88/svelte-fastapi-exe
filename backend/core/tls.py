"""TLS 검증 설정 공용 헬퍼.

사내망 HTTPS 소비자(updater·content_sync 의 GHE, log_collector 의 Loki)가 동일한
인증서 신뢰 규약을 공유하도록 한 곳에 모은다. certifi(Python 기본 CA 번들)는 Windows
인증서 저장소를 읽지 않아 사내 내부 CA 가 누락될 수 있는데, Windows 에서는
``ssl.create_default_context()`` 가 시스템 저장소를 신뢰하므로 이를 표준 경로로 쓴다.
"""

from __future__ import annotations

import ssl
import sys


def resolve_ssl_verify(verify_enabled: bool) -> bool | ssl.SSLContext:
    """httpx 의 ``verify`` 인자로 넘길 TLS 검증 설정을 결정한다.

    Args:
        verify_enabled: 인증서 검증 활성 여부. False 면 검증을 끈다
            (사내 자체 서명 인증서를 시스템에 등록하지 못한 최후 수단).

    Returns:
        bool | ssl.SSLContext:
            - ``False``: 검증 비활성.
            - ``ssl.SSLContext``: Windows 시스템 인증서 저장소(사내 CA 포함)를
              신뢰하는 컨텍스트.
            - ``True``: certifi 기본값(Linux/Mac).
    """
    if not verify_enabled:
        return False
    if sys.platform == "win32":
        return ssl.create_default_context()
    return True
