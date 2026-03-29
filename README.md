# computer-use-raw-python-executor

이 repo는 상시 실행 중인 endpoint로서 agent가 보낸 Python 코드를 Windows에서 그대로 실행하고, 현재 상태와 실행 결과를 다시 agent에 돌려주는 최소 executor repo입니다.

- 역할: execution endpoint
- 입력: observe/execute RPC
- 출력: 현재 상태와 실행 artifact
- transport: `stdio` 또는 `http`

executor는 프롬프트 의미를 해석하지 않습니다. 프롬프트와 policy는 agent가 들고 있고, executor는 상태 제공과 코드 실행만 합니다.
현재 상태 응답에는 transport 내부 `screenshot_base64`가 기본으로 들어갑니다.
`--screenshot-path`는 자동 캡처가 실패할 때만 쓰는 fallback입니다.

## 빠른 시작

```bash
cd /home/kss930/model-projects/gui-owl-8B-think-1.0.0/computer-use-raw-python-executor

./.venv/bin/python -m computer_use_raw_python_executor.cli \
  --transport stdio \
  --screenshot-path C:\\path\\to\\current_screen.png
```

## 남긴 파일

- `src/computer_use_raw_python_executor/cli.py`
- `src/computer_use_raw_python_executor/runner.py`
- `src/computer_use_raw_python_executor/models.py`
- `docs/EXECUTOR_CONTRACT.md`
- `docs/LOOP_ARCHITECTURE.md`

## 제거한 것

- payload JSON 수동 실행 경로
- `.py` 파일 수동 실행 경로
- task/prompt/loop 해석 경로
