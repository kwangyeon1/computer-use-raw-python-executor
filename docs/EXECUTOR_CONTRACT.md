# Executor Contract

## 역할

executor는 상시 실행 endpoint입니다.

- 현재 상태를 agent에 전달
- agent가 준 Python을 실행
- 실행 결과를 다시 agent에 전달

## RPC 액션

- `observe`
- `execute`

## 실행 흐름

1. agent가 `observe` 호출
2. executor가 자동 캡처를 시도하고 `screenshot_base64`, `observation_text` 반환
3. 자동 캡처 실패 시 `--screenshot-path` fallback을 사용
4. agent가 Python 생성 후 `execute` 호출
5. executor가 `generated.py` 저장 후 local Python으로 실행
6. stdout/stderr/metadata 저장
7. executor가 실행 기록과 `stdout_tail`/`stderr_tail`, `error_info`, 최신 상태를 agent에 반환

## 설계 원칙

- executor는 코드 meaning을 해석하지 않음
- code safety filtering을 하지 않음
- transport는 `stdio` 또는 `http`
- 실행 artifact는 executor 로컬 `artifact_root` 아래에 저장
- 현재 구조화된 실패 분류는 `ModuleNotFoundError`만 지원하며, `error_info.kind = "missing_python_module"`로 반환
