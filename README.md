# Svelte-FastAPI EXE

Vite-Svelte로 빌드한 LLM AI Agent 채팅 UI/UX를 FastAPI가 serving하는 exe 패키지

## 기술 스택
- Vite
- Svelte
- FastAPI
- Pyinstaller

## 패키지 매니저
- javascript: `npm`
- python: `uv`

## 환경 설정

1. 파이썬 가상 환경 및 의존 라이브러리 설치
```bash
uv sync --dev
```

2. Svelte 의존 라이브러리 설치
```bash
cd frontend
npm install
```

## 빌드

1. UI/UX 정적 파일 빌드 (vite)
```bash
cd frontend
npm run build
```

2. exe 파일 빌드 (pyinstaller)
```bash
uv run pyinstaller MyAgent.spec
```