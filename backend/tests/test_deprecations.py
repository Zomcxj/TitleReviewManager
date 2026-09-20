"""废弃 API 门禁测试（Python 3.12+）

背景：CI 此前只跑 Python 3.10，而 Docker 镜像与开发机都是 3.12。版本错位让
3.12 下的废弃警告在 CI 里完全不可见 —— 实际就漏掉了两处：
`datetime.utcnow()`（69 处）与 FastAPI 的 `@app.on_event`（3.12 起废弃）。

这里把门禁搬进 pytest，本地跑测试时就能拦住，不必等 CI。

只对**本项目模块**生效：第三方库内部的废弃警告（pydantic/fastapi/starlette）
不归我们管，让它们失败只会制造噪音并让人习惯性忽略门禁。
"""
import os
import re
import subprocess
import sys

import pytest

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 本项目自己的顶层模块
_OUR_MODULES = re.compile(
    r"^(main|routers|utils|tasks|models|schemas|enums|database|auth|storage"
    r"|db_bootstrap|seed|conftest)"
)


@pytest.mark.skipif(
    sys.version_info < (3, 12),
    reason="废弃告警只在 3.12+ 触发；CI 的 3.12 矩阵会执行此用例",
)
def test_no_self_inflicted_deprecation_warnings():
    """导入整个应用不应触发本项目代码自身的废弃警告。

    必须在子进程里跑：pytest 收集阶段往往已经把 main 及其依赖装进
    sys.modules，同进程内 `import main` 不会重新执行模块代码，警告也就不会
    再触发 —— 那样这个门禁永远不会失败（实测过：往 routers 里注入
    datetime.utcnow() 后同进程版本仍然「通过」）。

    子进程同时保证与 CI 的检查方式完全一致（CI 也是独立 python 进程）。
    会拉起全部 router（main.py 里逐个 include_router），覆盖面等于整个应用的
    导入路径。
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
    """生产代码不得再直接调用 datetime.utcnow()。

    必须走 utils.timeutil.utcnow() —— 它保持了 naive 语义（与库中读出的
    naive 值可直接比较），同时不在 3.12 触发废弃告警。
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
    """不得使用 @app.on_event —— 3.12 下废弃，应改用 lifespan。"""
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
    """不得使用 class Config —— Pydantic V2 起废弃，V3 将移除。"""
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
