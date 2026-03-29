# Raw Python Executor Profile

이 repo는 generated Python을 실행하는 executor endpoint입니다.

## 목표

- raw Python을 해석 없이 실행
- 현재 상태를 agent에 반환
- run artifact를 구조적으로 저장
- 모델 repo와 학습 repo를 executor 구현에서 분리

## 비목표

- safety sandbox
- environment rollback
- destructive capability filtering

## 입력 계약

- `observe`
- `execute`

## 출력 계약

- `generated.py`
- `stdout.log`
- `stderr.log`
- `execution.json`
- `events.jsonl`

## repo 계보

- pairs with: `../computer-use-raw-python-agent`
- runtime artifacts are consumed by: `../computer-use-stage1-raw-python`
