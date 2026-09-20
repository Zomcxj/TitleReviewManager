"""文档与路由一致性测试

起因：docs/api.md 长期滞后于代码 —— 7 个路由（备份、前端错误、Word 导入、
注册链接、导入导出、公海池）完全没写，且 `/api/batch/review` 是错的
（实际为 `/api/batch/review-batch`），照文档调用会 404。

这里做双向校验，让文档漂移在 CI 就暴露，而不是等用户照着文档调用失败：
- 文档写了但代码没有 → 文档在骗人，硬失败
- 代码有但文档没写 → 用户查不到，硬失败
"""

import pathlib
import re

import pytest

BACKEND = pathlib.Path(__file__).resolve().parent.parent
DOC = BACKEND.parent / "docs" / "api.md"
_ROUTER_DIR = BACKEND / "routers"


def _normalize(path: str) -> str:
    """把 {customer_id} / {mid} 等占位符统一成 {}，避免命名差异造成假差异。"""
    return re.sub(r"\{[^}]*\}", "{}", path)


def _code_endpoints() -> set[tuple[str, str]]:
    """从 routers/*.py 与 main.py 收集真实存在的端点。"""
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

        # 裸装饰器形式：@router.post("") 或 @router.get()
        for mm in re.finditer(r'@router\.(get|post|put|delete|patch)\(\s*\)', src):
            found.add((mm.group(1).upper(), _normalize(prefix + "/")))

    main_src = (BACKEND / "main.py").read_text(encoding="utf-8")
    for mm in re.finditer(r'@app\.(get|post)\(\s*"(/api/[^"]*)"', main_src):
        found.add((mm.group(1).upper(), _normalize(mm.group(2))))

    return found


def _documented_endpoints() -> set[tuple[str, str]]:
    """从 docs/api.md 的表格行里解析声明的端点。"""
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
        """文档声明的端点必须真实存在 —— 否则照文档调用会 404。"""
        phantom = sorted(_documented_endpoints() - _code_endpoints())
        assert not phantom, (
            "docs/api.md 声明了代码中不存在的端点（文档需修正）：\n"
            + "\n".join(f"  {m} {p}" for m, p in phantom)
        )

    def test_every_endpoint_is_documented(self):
        """代码中的端点必须都有文档 —— 否则用户无从得知。"""
        undocumented = sorted(_code_endpoints() - _documented_endpoints())
        assert not undocumented, (
            "以下端点未写入 docs/api.md：\n"
            + "\n".join(f"  {m} {p}" for m, p in undocumented)
        )

    def test_router_count_matches_registration(self):
        """每个 router 文件都应在 main.py 注册 —— 漏注册的路由等于不存在。"""
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
    """曾经缺失的章节不应再次消失。"""
    assert required_section in DOC.read_text(encoding="utf-8"), (
        f"docs/api.md 缺少章节: {required_section}"
    )
