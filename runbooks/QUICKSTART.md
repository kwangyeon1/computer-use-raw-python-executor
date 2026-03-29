# Quickstart

```bash
cd /home/kss930/model-projects/gui-owl-8B-think-1.0.0/computer-use-raw-python-executor
python3 -m venv .venv
./.venv/bin/python -m pip install -e '.[dev]'
```

executor service 실행:

```bash
./.venv/bin/python -m computer_use_raw_python_executor.cli \
  --transport stdio \
  --screenshot-path C:\\path\\to\\current_screen.png
```
