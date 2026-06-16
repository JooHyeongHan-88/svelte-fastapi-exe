# 앱 생명주기 · Presence · 동시성 · Origin 가드

`backend_architecture.md` 에서 발췌. 인프라 계층(경로 분기·기동 시퀀스·브라우저 생존
신호·스레드 안전·보안 경계)을 다룬다.

에이전트·하니스·차트·프론트엔드는 각각 별도 문서 참고.

---

## PyInstaller frozen 경로 분기

`backend/core/config.py`의 `_project_root()`가 모든 경로의 단일 진실 공급원.

| 모드 | 루트 | 정적 자산 | Updater |
|---|---|---|---|
| frozen EXE | `sys._MEIPASS` | `MEIPASS/web` | `MEIPASS/updater/Updater.exe` |
| dev | 프로젝트 루트 | `build/web/` | — |

> **새 정적 자산을 추가할 때** -> `packaging/App.spec`의 `datas`에도 등록 필수.
> `PROMPTS/`, `SKILLS/`, `AGENTS/` 는 디렉터리 단위로 이미 등록됐으므로 파일 추가만으로 다음 빌드에 반영된다.
>
> **`backend/scripts/` 패키지**: `backend/` 가 PyInstaller `pathex` 에 포함되므로 `scripts/` 는 일반 Python 패키지(`__init__.py` 필수)로 자동 인식된다. `App.spec` 이 `collect_submodules('scripts')` 를 실행하므로 파일을 추가하면 다음 빌드에서 자동 번들링된다.
>
> **`APP_ALLOWED_LIBRARIES` 자동 번들링**: `App.spec` 이 빌드 시 `.env` 의 `APP_ALLOWED_LIBRARIES` 를 읽어 각 패키지에 `collect_all()` 을 실행한다. `.env` 한 줄 추가만으로 dev 런타임과 EXE 번들 양쪽에서 동시 사용 가능.

---

## App 생명주기 (EXE 기동 시)

0. `core.server_socket.create_server_socket()` -> APP_PORT 또는 APP_NAME 해시(47100-48999) 기반 고정 포트에 바인딩.
   같은 앱이 이미 실행 중이면 `ServerAlreadyRunning` 예외 -> 기존 인스턴스 탭 열고 `sys.exit(0)` (단일 인스턴스).
   포트 점유 시 +1..+4 후보 체인 자동 폴백. 전수 실패 시 동적 포트 최후수단.
1. `backend/main.py` -> `uvicorn.Config + Server` 생성, `browser.server`에 보관
   (Windows `os.kill(SIGTERM)`은 lifespan shutdown을 실행하지 않으므로 `server.should_exit = True` 경로만 사용)
2. watchdog + open_browser 데몬 스레드 시작 -> `server.run()`
3. 브라우저 로드 -> `initApp()`이 localStorage에서 세션 복원
   - 세션이 있으면 활성 세션 ID로, 없으면 `BROWSER_KEEPALIVE_ID`로 `/api/presence` EventSource 오픈
4. `browser.connect_client(id)` 호출 - 연결 유지 = 생존 신호. `KEEPALIVE_INTERVAL`(30s)마다 `: ping`으로 idle timeout 방지
5. 탭 닫기 -> EventSource 종료 -> `finally`에서 `browser.disconnect_client` -> `PRESENCE_RECONNECT_GRACE`(2s) 후 실제 제거
6. `browser.watchdog`이 클라이언트 부재 감지 -> `SHUTDOWN_GRACE` 경과 시 `server.should_exit = True`

### Presence 설계 원칙

`presenceSource`는 탭당 1개. 세션이 있으면 해당 세션 ID, 없으면 `BROWSER_KEEPALIVE_ID`로 연결한다.
세션 삭제와 서버 생존을 분리함으로써 **모든 세션을 삭제해도 브라우저가 열려 있는 한 서버는 유지**된다.

```
세션 있음  -> openPresence(sessionId)
세션 전부 삭제  -> openPresence(BROWSER_KEEPALIVE_ID)   <- 서버 종료 방지
탭 닫기  -> EventSource 자동 종료 -> disconnect -> watchdog -> shutdown
```

---

## 동시성 모델

`backend/core/browser.py`의 `_connections: dict[str, int]`과 `_pending_disconnects: dict[str, threading.Timer]`는
**uvicorn event-loop · watchdog 스레드 · `threading.Timer` 콜백** 3곳에서 동시 접근한다.

- 모든 read/write는 `_lock` 안에서 수행
- 순회는 `_snapshot()`이 `dict`를 락 안에서 스냅샷한 뒤 락 밖에서 처리
- `Timer.cancel()` / `Timer.start()`는 자체 락을 가지므로 우리 `_lock` **밖**에서 호출 (lock ordering 준수)
- 탭 복제(같은 client_id 공유) 대응: `_connections` 값을 카운트로 관리 - 마지막 연결이 끊겨야 grace 진입
- `_ever_registered` 플래그로 "최초 연결 이전 STARTUP_GRACE 대기"와 "연결 후 비어있음(SHUTDOWN_GRACE)"을 구분

---

## Origin 가드 (보안 경계)

`backend/api/deps.py`의 `require_local_origin` 의존성이 router 레벨에 적용된다.

- **frozen(EXE)** 에서만 활성. dev는 Vite proxy 때문에 origin이 달라 자동 패스.
- `Origin` 헤더 있으면 `ALLOWED_ORIGIN`(`http://{HOST}:{실제 바인딩 포트}`)과 일치 확인.
  포트는 `core.server_socket.create_server_socket()` -> `set_runtime_port()`로 기동 시 갱신되므로,
  `deps.py` 는 import 스냅샷이 아니라 `config.ALLOWED_ORIGIN` 을 매 요청 참조한다.
  단일 인스턴스 프로브(`_probe_same_app`)도 Origin/sec-fetch-site 없이 stdlib urllib 로 요청해 이 가드를 통과한다.
- 없으면 `sec-fetch-site`가 `same-origin` / `none` 이어야 통과
