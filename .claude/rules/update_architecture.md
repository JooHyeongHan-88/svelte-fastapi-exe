# 업데이트 & 릴리즈 아키텍처

## 자동 업데이트 — 4단계 흐름

```
① check_latest()    REPO_BASE_URL/latest.json GET, 5분 캐시
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

## Release 빌드 순서 (extensions 포함)

`release.ps1` 빌드 순서: ① pyproject 버전 읽기 → ② **메인 프론트**(`frontend` → `build/web/`)
→ ③ **확장 프론트**(`extensions/*/frontend` → 각 `dist/`) → ④ Updater.exe → ⑤ App EXE(App.spec)
→ ⑥ sha256·latest.json → ⑦ 업로드(`-Upload`).

- **③ 확장 프론트 빌드가 ⑤ App.spec 보다 먼저**여야 한다. `App.spec` 은 `extensions/<tool>/frontend/dist`
  가 **있을 때만** 번들하므로(→ `extensions_architecture.md`), 빌드를 건너뛰면 stale/누락 dist 가
  EXE 에 박힌다. 확장은 폴더 컨벤션(`*/frontend/package.json`)으로 자동 발견 — 새 확장을 추가해도
  release.ps1 수정 불필요.
- **격리**: 한 확장의 `npm` 빌드 실패는 메인 앱 릴리즈를 막지 않는다(경고 후 계속). App.spec 은 그 경우
  기존 dist 만 번들하거나, 없으면 그 확장을 건너뛴다(빈손 no-op).
- `node_modules` 부재 시에만 설치(`package-lock.json` 있으면 `npm ci`, 없으면 `npm install`) 후 `npm run build`.
- `release-dryrun.ps1` 은 release.ps1 을 호출하므로 확장 빌드를 그대로 상속하며, 끝에 각 확장의
  `dist`/`router` 번들 존재를 확인 출력한다. 수동 검증 시나리오 `[E]` 가 `/ext/<tool>/` 진입을 안내한다.

## Release 스크립트 — PowerShell 5.1 주의점

- `param()` 블록은 **반드시 첫 실행문** (앞에 `[Console]::OutputEncoding=` 두면 파싱 에러)
- `latest.json`은 **BOM 없는 UTF-8** — `[System.IO.File]::WriteAllText(path, content, (New-Object System.Text.UTF8Encoding $false))` 사용  
  (`Set-Content -Encoding utf8`은 BOM 붙어 `Invoke-RestMethod` 파싱 실패)
- `backend/_version.py`는 gitignored 생성물. **App.spec이 Analysis 전에** `tomllib`으로 pyproject.toml 파싱 후 자동 생성한다. release.ps1은 더 이상 이 파일을 쓰지 않는다.
- `Write-Host` 한글 깨짐 → 스크립트 출력은 영어 유지
- 저장소 업로드 순서: **EXE 먼저 → latest.json 마지막** (클라이언트가 404 EXE 보지 않도록)
