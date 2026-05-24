# 백엔드 아키텍처

## PyInstaller frozen 경로 분기

`backend/core/config.py`의 `_project_root()`가 모든 경로의 단일 진실 공급원.

| 모드 | 루트 | 정적 자산 | Updater |
|---|---|---|---|
| frozen EXE | `sys._MEIPASS` | `MEIPASS/web` | `MEIPASS/updater/Updater.exe` |
| dev | 프로젝트 루트 | `build/web/` | — |

> **새 정적 자산을 추가할 때** → `packaging/App.spec`의 `datas`에도 등록 필수.  
> `PROMPTS/`, `SKILLS/` 는 디렉터리 단위로 이미 등록됐으므로 파일 추가만으로 다음 빌드에 반영된다.

---

## App 생명주기 (EXE 기동 시)

1. `backend/main.py` → `uvicorn.Config + Server` 생성, `browser.server`에 보관  
   (Windows `os.kill(SIGTERM)`은 lifespan shutdown을 실행하지 않으므로 `server.should_exit = True` 경로만 사용)
2. watchdog + open_browser 데몬 스레드 시작 → `server.run()`
3. 브라우저 로드 → `initApp()`이 localStorage에서 세션 복원  
   - 세션이 있으면 활성 세션 ID로, 없으면 `BROWSER_KEEPALIVE_ID`로 `/api/presence` EventSource 오픈
4. `browser.connect_client(id)` 호출 — 연결 유지 = 생존 신호. `KEEPALIVE_INTERVAL`(30s)마다 `: ping`으로 idle timeout 방지
5. 탭 닫기 → EventSource 종료 → `finally`에서 `browser.disconnect_client` → `PRESENCE_RECONNECT_GRACE`(2s) 후 실제 제거
6. `browser.watchdog`이 클라이언트 부재 감지 → `SHUTDOWN_GRACE` 경과 시 `server.should_exit = True`

### Presence 설계 원칙

`presenceSource`는 탭당 1개. 세션이 있으면 해당 세션 ID, 없으면 `BROWSER_KEEPALIVE_ID`로 연결한다.  
세션 삭제와 서버 생존을 분리함으로써 **모든 세션을 삭제해도 브라우저가 열려 있는 한 서버는 유지**된다.

```
세션 있음  → openPresence(sessionId)
세션 전부 삭제  → openPresence(BROWSER_KEEPALIVE_ID)   ← 서버 종료 방지
탭 닫기  → EventSource 자동 종료 → disconnect → watchdog → shutdown
```

---

## 동시성 모델

`backend/core/browser.py`의 `_connections: dict[str, int]`과 `_pending_disconnects: dict[str, threading.Timer]`는  
**uvicorn event-loop · watchdog 스레드 · `threading.Timer` 콜백** 3곳에서 동시 접근한다.

- 모든 read/write는 `_lock` 안에서 수행
- 순회는 `_snapshot()`이 `dict`를 락 안에서 스냅샷한 뒤 락 밖에서 처리
- `Timer.cancel()` / `Timer.start()`는 자체 락을 가지므로 우리 `_lock` **밖**에서 호출 (lock ordering 준수)
- 탭 복제(같은 client_id 공유) 대응: `_connections` 값을 카운트로 관리 — 마지막 연결이 끊겨야 grace 진입
- `_ever_registered` 플래그로 "최초 연결 이전 STARTUP_GRACE 대기"와 "연결 후 비어있음(SHUTDOWN_GRACE)"을 구분

---

## Origin 가드 (보안 경계)

`backend/api/deps.py`의 `require_local_origin` 의존성이 router 레벨에 적용된다.

- **frozen(EXE)** 에서만 활성. dev는 Vite proxy 때문에 origin이 달라 자동 패스.
- `Origin` 헤더 있으면 `ALLOWED_ORIGIN`(`http://127.0.0.1:8765`)과 일치 확인
- 없으면 `sec-fetch-site`가 `same-origin` / `none` 이어야 통과

---

## 에이전트 하니스 구조

`backend/agent/harness.py`의 `run_turn()` 한 번 = 사용자 입력 1건에 대한 완전한 응답 턴.

```
run_turn(client_id, user_message, *, force_skills=None, ...)
   │
   ├─ state_store.get(client_id)          → AgentState (todo / missing_slots)
   ├─ force_skills ? get_by_names()       → SKILLS body lazy load
   │            : skill_registry.select() → trigger / name 매칭
   ├─ PromptRegistry.compose()            → PROMPTS/base.md + safety.md
   ├─ _compose_system_prompt()            → base + skill bodies + todo/pending 요약
   │    └─ 스킬 2개 이상이면 멀티스킬 플래닝 지침 자동 주입
   │
   ├─ yield SkillActiveEvent              → 프론트 뱃지 즉시 표시
   │
   └─ for iteration in range(max_iterations):
        provider.astream(messages, tools)
          ├─ delta       → yield 그대로 전달
          ├─ tool_call   → 분기
          │    ├─ add_todo / complete_todo  → AgentState 직접 갱신 + TodoUpdateEvent
          │    ├─ 슬롯 가드 실패             → AskUserEvent + 안전 종료
          │    └─ 정상 도구                 → _execute_tool + ToolResultEvent
          └─ done → break
   │
   └─ store.append + state_store.set + DoneEvent
```

### PROMPTS / SKILLS 로딩 정책

| 디렉터리 | 로딩 시점 | 캐시 정책 |
|---|---|---|
| `PROMPTS/` | 매 턴 `_read()` 호출 | dev: mtime 변경 시 재로드 (핫리로드) / frozen: 1회 |
| `SKILLS/` Front Matter | 부팅 시 `load()` 1회 | 메모리 캐시 고정 |
| `SKILLS/` body | 매칭된 스킬 첫 호출 시 lazy | dev: mtime 재검사 / frozen: 1회 |
