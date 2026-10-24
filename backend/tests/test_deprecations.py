"""Deprecated API gate tests (Python 3.12+)

Background: CI used to run only Python 3.10 while the Docker image and dev
machines are 3.12. The version mismatch made deprecation warnings under 3.12
invisible in CI — and two things indeed slipped through:
`datetime.utcnow()` (69 occurrences) and FastAPI's `@app.on_event`
(deprecated as of 3.12).

This moves the gate into pytest so running tests locally catches it without
waiting for CI.

Applies only to **this project's modules**: deprecation warnings inside
third-party libraries (pydantic/fastapi/starlette) are not our problem;
making them fail only creates noise and trains people to ignore the gate.
"""
import os
import re
import subprocess
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# This project's own top-level modules
_OUR_MODULES = re.compile(
    r"^(main|routers|utils|tasks|models|schemas|enums|database|auth|storage"
    r"|db_bootstrap|seed|conftest)"
)


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="废弃告警只在 3.12+ 触发；CI 的 3.12 矩阵会执行此用例",
)
def test_no_self_inflicted_deprecation_warnings():
    """Importing the whole app must not trigger deprecation warnings from this project's own code.

    Must run in a subprocess: pytest collection has usually already loaded main
    and its dependencies into sys.modules, so an in-process `import main` will
    not re-execute module code and the warnings will not fire again — the gate
    would then never fail (verified in practice: after injecting
    datetime.utcnow() into routers, the in-process version still "passed").

    The subprocess also guarantees the check matches CI exactly (CI also runs a
    separate python process). It spins up every router (include_router one by
    one in main.py), covering the whole application's import paths.
    """
    script = (
        "import warnings\n"
        "warnings.filterwarnings('error', category=DeprecationWarning,"
        f" module=r'{_OUR_MODULES.pattern}')\n"
        "warnings.filterwarnings('error', category=PendingDeprecationWarning,"
        f" module=r'{_OUR_MODULES.pattern}')\n"
        "import main\n"
        "print('OK')\n"
    )
    env = dict(os.environ)
    env.setdefault("JWT_SECRET_KEY", "deprecation-test")
    env.setdefault("SCHEDULER_ENABLED", "0")
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True, text=True, env=env, cwd=BACKEND_DIR,
    )
    assert result.returncode == 0, (
        "本项目代码触发了废弃告警（将在未来 Python 版本移除，需改用新 API）:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "OK" in result.stdout


def test_utcnow_helper_is_used_not_datetime_utcnow():
    """Production code must no longer call datetime.utcnow() directly.

    It must go through utils.timeutil.utcnow() — which keeps naive semantics
    (directly comparable with naive values read from the database) and does not
    trigger a deprecation warning on 3.12.
    """
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    offenders = []
    for py in backend.rglob("*.py"):
        rel = py.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "alembic/")) or rel == "utils/timeutil.py":
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "datetime.utcnow()" in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")

    assert not offenders, (
        "以下位置仍直接调用 datetime.utcnow()（3.12 起废弃），"
        "应改用 utils.timeutil.utcnow():\n" + "\n".join(f"  {o}" for o in offenders)
    )


def test_no_fastapi_on_event():
    """@app.on_event must not be used — deprecated on 3.12; use lifespan instead."""
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    offenders = []
    for py in backend.rglob("*.py"):
        rel = py.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "alembic/")):
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if "on_event(" in line:
                offenders.append(f"{rel}:{i}: {line.strip()}")

    assert not offenders, (
        "以下位置仍使用已废弃的 @app.on_event，应改用 lifespan:\n"
        + "\n".join(f"  {o}" for o in offenders)
    )


def test_no_pydantic_class_based_config():
    """class Config must not be used — deprecated since Pydantic V2 and removed in V3."""
    from pathlib import Path

    backend = Path(__file__).resolve().parent.parent
    offenders = []
    for py in backend.rglob("*.py"):
        rel = py.relative_to(backend).as_posix()
        if rel.startswith(("tests/", "alembic/")):
            continue
        for i, line in enumerate(py.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip() == "class Config:":
                offenders.append(f"{rel}:{i}")

    assert not offenders, (
        "以下位置仍使用 class-based Config（Pydantic V2 废弃），"
        "应改用 model_config = ConfigDict(...):\n" + "\n".join(f"  {o}" for o in offenders)
    )
