# 업데이트 & 릴리즈 아키텍처

## 자동 업데이트 — 4단계 흐름

```
① check_latest()    NEXUS_BASE_URL/latest.json GET, 5분 캐시
                    URL prefix·sha256 hex(64자) 검증 → 실패 시 silently update_available=False
② apply_update()    스트리밍 다운로드 → sha256 검증 → {stem}.new.exe staging
                    → DETACHED Updater.exe Popen(pid, new, current) → 1s 후 server.should_exit
③ Updater.exe       부모 pid 폴링(최대 60s) → POST_EXIT_GRACE 3s 추가 대기
④ rename-to-backup  current → .old (rename은 잠긴 파일도 허용)
                    → new → current → 실패 시 .old 복원 후 재기동
```

**절대 변경 금지**: 방금 종료된 EXE의 잔존 잠금 + AV 스캔 때문에 `os.replace(new, current)` 직접 시도는
`ERROR_ACCESS_DENIED` 발생. **rename-to-backup 전략**으로 30회 × 0.5s 재시도. 이 전략으로 회귀시키지 말 것.

진행 상태: `GET /api/update/status` → `{status, progress, total, message, target_version}`  
(`idle|downloading|verifying|staging|restarting|error`)

---

## Release 스크립트 — PowerShell 5.1 주의점

- `param()` 블록은 **반드시 첫 실행문** (앞에 `[Console]::OutputEncoding=` 두면 파싱 에러)
- JSON·`_version.py`는 **BOM 없는 UTF-8** — `[System.IO.File]::WriteAllText(path, content, (New-Object System.Text.UTF8Encoding $false))` 사용  
  (`Set-Content -Encoding utf8`은 BOM 붙어 `Invoke-RestMethod` 파싱 실패)
- `Write-Host` 한글 깨짐 → 스크립트 출력은 영어 유지
- Nexus 업로드 순서: **EXE 먼저 → latest.json 마지막** (클라이언트가 404 EXE 보지 않도록)
