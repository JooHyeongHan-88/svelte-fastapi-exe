"""사내 원격 raw repository(현재 Nexus) 에 릴리스 산출물을 업로드한다.

release.ps1 의 -Upload 플래그로 호출된다.
업로드 대상 (순서 준수):
  1. release/{AppName}.exe           — 최신 바이너리 (latest.json url 이 가리킴)
  2. release/{AppName}-{version}.exe — 버전 아카이브
  3. release/latest.json             — 메타데이터 (EXE 업로드 완료 후 마지막)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

_root = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=_root / ".env", override=False)


def _require_env(key: str) -> str:
    val = os.getenv(key)
    if not val:
        print(f"ERROR: {key} is not set. Check .env or environment variables.")
        sys.exit(1)
    return val


def _upload_file(
    client: httpx.Client, base_url: str, local_path: Path, remote_name: str
) -> None:
    url = f"{base_url}/{remote_name}"
    print(f"  uploading {local_path.name} -> {url}")
    with local_path.open("rb") as f:
        r = client.put(url, content=f)
        r.raise_for_status()
    print(f"  done ({local_path.stat().st_size:,} bytes)")


def main() -> None:
    base_url = _require_env("APP_REPO_BASE_URL").rstrip("/")
    username = _require_env("APP_REPO_USER")
    password = _require_env("APP_REPO_PASSWORD")
    app_name = os.getenv("APP_NAME", "MyAgent")

    release_dir = _root / "release"

    # 업로드 대상 — (로컬 경로, 원격 파일명). EXE 먼저, latest.json 마지막.
    targets: list[tuple[Path, str]] = []

    plain_exe = release_dir / f"{app_name}.exe"
    if plain_exe.is_file():
        targets.append((plain_exe, f"{app_name}.exe"))

    for p in sorted(release_dir.glob(f"{app_name}-*.exe")):
        targets.append((p, p.name))

    latest_json = release_dir / "latest.json"
    if latest_json.is_file():
        targets.append((latest_json, "latest.json"))

    if not targets:
        print("ERROR: no files found in release/")
        sys.exit(1)

    print(f"uploading {len(targets)} file(s) to {base_url}")

    with httpx.Client(auth=(username, password), timeout=120) as client:
        for local_path, remote_name in targets:
            _upload_file(client, base_url, local_path, remote_name)

    print("all uploads complete")


if __name__ == "__main__":
    main()
