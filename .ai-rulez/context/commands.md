---
priority: high
---

# Commands

- Use **uv**. Install dependencies with `uv sync`.

| Task | Command |
| ---- | ------- |
| Run the app | `uv run keycast` |
| CLI subcommands | `uv run keycast version` · `uv run keycast info` |
| Run all tests | `uv run python -m pytest` |
| Run one module | `uv run python -m pytest tests/test_settings.py` |
| Run one test | `uv run python -m pytest -k test_rotation_defaults` |
| Coverage (config in `pyproject.toml`) | `uv run pytest --cov` |
| Full test matrix | `uv run --locked tox run` |
| Lint + type-check | `uv run --locked tox run -e style` |
| Git hooks | `uv run --locked tox run -e prek` |
| Build package | `uv build` |
