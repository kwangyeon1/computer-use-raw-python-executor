# Loop Architecture

## 목표

agent가 loop driver가 되고 executor는 endpoint가 됩니다.

```text
observe current screen from executor
-> generate python in agent
-> send python code to executor
-> execute code locally
-> return next state + logs
-> repeat
```

## transport 옵션

- `stdio`
- `http`

## executor가 담당하는 것

- screenshot path 제공
- execution result 요약
- artifact 저장

## agent가 담당하는 것

- 사용자 prompt/policy 보관
- 현재 화면/이전 결과를 보고 다음 Python 생성
- 필요하면 `done` 판단
