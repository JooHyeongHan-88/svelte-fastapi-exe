# LLM 설정 아키텍처

## 설정 저장 위치

| 항목 | 저장 위치 | 비고 |
|---|---|---|
| provider, model, api_key, base_url | `settings.json` | `SettingsStore`로 관리 |
| temperature, max_tokens | `.env` / 환경 변수 (`APP_LLM_TEMPERATURE` 등) | settings.json에 저장 안 함 |
| system_prompt | `.env` / 환경 변수 (`APP_SYSTEM_PROMPT`) | settings.json에 저장 안 함 |
| 세션·메시지 | 브라우저 localStorage | 백엔드 미저장 |

`settings.json` 경로:
- **dev**: `backend/settings/settings.json`
- **frozen EXE**: `%APPDATA%\{APP_NAME}\settings.json`

## SettingsStore — threading.Lock 주의

`backend/settings/store.py`의 `SettingsStore`는 `threading.Lock`을 사용한다.
Python `threading.Lock`은 **non-reentrant** — 같은 스레드에서 두 번 `acquire()` 하면 데드락.

`update()` 내에서 절대 `self.get()`을 호출하지 말 것 (get도 lock을 잡는다).
락 안에서는 `self._cache`를 직접 참조한다.

```python
# ✅ 올바른 패턴
with self._lock:
    if self._cache is None:
        self._load()
    update_dict = self._cache.model_dump()
    ...

# ❌ 데드락 발생
with self._lock:
    current = self.get()   # self._lock 재취득 → 영원히 대기
```

## API Key 보안 규칙

1. API 키는 `settings.json`에만 저장. **브라우저 localStorage에는 절대 저장하지 않는다.**
2. `GET /api/settings` 응답에서 api_key는 항상 마스킹(`sk-p••••••4f2a` 형식).
   마스킹 로직은 `backend/settings/masking.py` 단일 지점에서 처리.
3. 에러 메시지에 API 키 평문이 포함되지 않도록 주의.
4. `POST /api/settings`에서 `api_key: null`은 "변경 없음", `""` (빈 문자열)은 "키 삭제".

## 프론트엔드 설정 모달 흐름

```
openSettings()
  ├─ GET /api/settings          → draft._maskedKey (마스킹된 현재 키)
  ├─ GET /api/settings/providers → ui.providers
  └─ ui.settingsDraft = { provider, model, api_key: "", ... }
       └─ api_key 입력 필드는 항상 빈칸으로 시작 (마스킹키는 placeholder용)

saveSettings()
  └─ POST /api/settings (patch)
       ├─ clearKey=true  → api_key: ""  (키 삭제)
       ├─ api_key 입력됨 → api_key: <새 키>
       └─ 아무것도 안 했으면 → api_key: null (백엔드가 무시 = 기존 유지)

testConnectionAction()
  └─ POST /api/settings/test
       └─ api_key 비어있으면 백엔드가 동일 provider의 저장된 키 fallback 사용
```

## 프로바이더 hot-swap

`/api/chat` 요청마다 `_settings_store.get()`으로 최신 설정을 읽고 `get_provider(settings)`로 인스턴스를 즉시 생성한다. 서버 재시작 없이 프로바이더 전환이 적용된다.

## 새 프로바이더 추가 방법

1. `backend/chat/providers/<name>.py` 생성 — `astream(messages, tools)` AsyncGenerator 구현
2. `backend/chat/providers/factory.py`의 `get_provider()`에 분기 추가
3. `backend/settings/models.py`의 `Literal["mock", "openai_compatible", "<name>"]`에 추가
4. `backend/routers/api.py`의 `list_providers()`에 `ProviderMeta` 항목 추가
5. `backend/settings/store.py`는 변경 불필요 (Pydantic이 알 수 없는 Literal값은 ValidationError)

기존 `settings.json`에 새 provider 값이 없으면 로드 실패할 수 있으므로, Literal 변경 전에 마이그레이션 또는 기본값 처리 고려.
