"""Docs vs routes consistency tests

Origin: docs/api.md lagged behind the code for a long time — 7 routes (backup,
frontend errors, Word import, registration links, import/export, public pool)
were entirely missing, and `/api/batch/review` was wrong (actually
`/api/batch/review-batch`), so calls made per the docs would 404.

This does bidirectional validation so doc drift surfaces in CI instead of
waiting for users to fail while following the docs:
- documented but not in code → the docs are lying, hard fail
- in code but not documented → users cannot find it, hard fail
"""

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
DOC = BACKEND.parent / "docs" / "api.md"
_ROUTER_DIR = BACKEND / "routers"


def _normalize(path: str) -> str:
    """Normalize placeholders like {customer_id} / {mid} into {} to avoid false diffs from naming differences."""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _code_endpoints() -> set[tuple[str, str]]:
    """Collect the endpoints that actually exist from routers/*.py and main.py."""
    found: set[tuple[str, str]] = set()

    for py in sorted(_ROUTER_DIR.glob("*.py")):
        src = py.read_text(encoding="utf-8")
        m = re.search(r'prefix="([^"]*)"', src)
        if not m:
            continue
        prefix = m.group(1).rstrip("/")

        for mm in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*["\']([^"\']*)["\']', src):
            method, path = mm.group(1).upper(), mm.group(2)
            full = prefix + ("/" + path.strip("/") if path.strip("/") else "/")
            found.add((method, _normalize(full)))

        # Bare decorator forms: @router.post("") or @router.get()
        for mm in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*\)', src):
            found.add((mm.group(1).upper(), _normalize(prefix + "/")))

    main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
    for mm in re.finditer(r'@app\.(get|post)\(\s*"(/api/[^"]*)"', main_src):
        found.add((mm.group(1).upper(), _normalize(mm.group(2))))

    return found


def _documented_endpoints() -> set[tuple[str, str]]:
    """Parse the endpoints declared in table rows of docs/api.md."""
    found: set[tuple[str, str]] = set()
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if not line.startswith("|") or "/api/" not in line:
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        paths = re.findall(r"`([^`]+)`", cells[0]) or [cells[0]]
        methods = re.findall(r"\b(GET|POST|PUT|DELETE|PATCH)\b", cells[1])
        if not methods:
            continue
        for path in paths:
            if not path.startswith("/api/"):
                continue
            for method in methods:
                found.add((method, _normalize(path)))
    return found


class TestApiDocsMatchRoutes:
    def test_doc_file_exists(self):
        assert DOC.exists(), f"API 文档缺失: {DOC}"

    def test_every_documented_endpoint_exists(self):
        """Every documented endpoint must really exist — otherwise calls per the docs will 404."""
        phantom = sorted(_documented_endpoints() - _code_endpoints())
        assert not phantom, (
            "docs/api.md 声明了代码中不存在的端点（文档需修正）：\n"
            + "\n".join(f"  {m} {p}" for m, p in phantom)
        )

    def test_every_endpoint_is_documented(self):
        """Every endpoint in code must be documented — otherwise users have no way to discover it."""
        undocumented = sorted(_code_endpoints() - _documented_endpoints())
        assert not undocumented, (
            "以下端点未写入 docs/api.md：\n"
            + "\n".join(f"  {m} {p}" for m, p in undocumented)
        )

    def test_router_count_matches_registration(self):
        """Every router file must be registered in main.py — an unregistered route might as well not exist."""
        main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
        registered = set(re.findall(r"app\.include_router\((\w+)\.router\)", main_src))
        missing = []
        for py in sorted(_ROUTER_DIR.glob("*.py")):
            name = py.stem
            if name.startswith("_") or name == "__init__":
                continue
            if name not in registered:
                missing.append(name)
        assert not missing, f"以下 router 未在 main.py 注册: {missing}"


@pytest.mark.parametrize("required_section", [
    "## 认证",
    "## 客户管理",
    "## 审核",
    "## 审计",
    "## 数据备份（管理员）",
    "## 前端错误上报",
    "## Word 表单导入",
    "## 专属注册链接",
    "## 批量导入导出",
    "## 公海池",
])
def test_documented_sections_present(required_section):
    """Sections that were once missing must not disappear again."""
    assert required_section in DOC.read_text(encoding="utf-8"), (
        f"docs/api.md 缺少章节: {required_section}"
    )
