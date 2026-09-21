"""部署配置一致性：docker-compose.yml / Dockerfile 必须真的把配置传进容器。

背景（这次修的真实缺陷）：
- `Dockerfile` 只装了 `libpq5`，没有 `postgresql-client` → 容器内没有 `pg_dump`
  → PostgreSQL 下自动备份永远失败（只会在凌晨 3 点发一条站内通知）。
- `docker-compose.yml` 不使用 `env_file`，`.env` 里的变量必须在 `environment`
  段逐个列出才生效，而 `BACKUP_*` / `TRUST_PROXY` 等一个都没列
  → 用户在 `.env` 里精心配置的备份目录、保留份数、HTTPS 开关全部被静默忽略。
- 没有任何卷挂载备份目录 → 默认落在 `/app/backups`，容器重建即丢。

这类缺陷的共同点是「配置看起来配了，实际没生效」，且只在生产才暴露，
所以用测试把「代码读的环境变量」与「compose 转发的环境变量」对齐。
"""
import re
from pathlib import Path

import pytest
import yaml

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent
COMPOSE_FILE = PROJECT_ROOT / "docker-compose.yml"
DOCKERFILE = PROJECT_ROOT / "Dockerfile"


@pytest.fixture(scope="module")
def compose() -> dict:
    return yaml.safe_load(COMPOSE_FILE.read_text(encoding="utf-8"))


def _backend_env(compose: dict) -> dict:
    return compose["services"]["backend"]["environment"]


def _backend_volumes(compose: dict) -> list:
    return compose["services"]["backend"]["volumes"]


def _env_var_names_read_by_code() -> set:
    """扫描 backend 源码，收集所有被读取的环境变量名。

    覆盖两种写法：
    - os.getenv("NAME") / os.environ["NAME"] / os.environ.get("NAME")
    - _env_flag("NAME", ...) 之类的本项目辅助函数（用字面量参数调用）
    """
    names = set()
    patterns = [
        re.compile(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(r'os\.environ(?:\.get)?[\(\[]\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(r'_env_flag\(\s*"([A-Z][A-Z0-9_]*)"'),
    ]
    for py in BACKEND_DIR.rglob("*.py"):
        # 测试自身不算部署配置的读取方
        if "tests" in py.parts or "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pat in patterns:
            names.update(pat.findall(text))
    return names


# 这些变量由 compose 自己消费（不是传给应用容器），或由基础镜像/运行环境提供，
# 不该要求出现在 backend 服务的 environment 里。
_COMPOSE_INTERNAL = {
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "APP_PORT",
}
_IMAGE_PROVIDED = {
    "FRONTEND_DIST", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "PATH", "HOME", "HOSTNAME",
}
# 只在特定部署方式下才需要，且默认值就是正确的安全默认（单机直连）。
# 仍应转发，但允许它们不出现在 compose 里时不报错 —— 见下方 test_security_vars_forwarded。
_OPTIONAL = {"APP_VERSION", "SCHEDULER_STARTUP_DELAY"}


class TestComposeForwardsAppConfig:
    def test_backup_vars_are_forwarded(self, compose):
        """备份相关变量必须转发：否则 .env 里的配置全部被忽略。

        这是最要命的一类 —— 用户以为设了 BACKUP_DIR/BACKUP_KEEP，
        实际应用仍在用默认值，且没有任何报错。
        """
        env = _backend_env(compose)
        for name in (
            "BACKUP_ENABLED", "BACKUP_DIR", "BACKUP_KEEP", "BACKUP_HOUR",
            "BACKUP_INCLUDE_FILES", "BACKUP_COMPRESS", "BACKUP_DRILL_ENABLED",
        ):
            assert name in env, f"docker-compose.yml 未转发 {name}，.env 中的设置不会生效"

    def test_backup_dir_points_into_a_mounted_volume(self, compose):
        """备份目录必须落在挂载卷内，否则容器重建时备份一起消失。"""
        env = _backend_env(compose)
        # 形如 ${BACKUP_DIR:-/data/backups} —— 取出默认值
        m = re.search(r"-(/.+?)\}", str(env["BACKUP_DIR"]))
        resolved = m.group(1) if m else str(env["BACKUP_DIR"])

        mount_targets = [
            v.split(":")[1] for v in _backend_volumes(compose) if v.count(":") >= 1
        ]
        assert any(
            resolved == t or resolved.startswith(t.rstrip("/") + "/")
            for t in mount_targets
        ), f"BACKUP_DIR={resolved} 不在任何挂载卷内，容器重建会丢备份；卷: {mount_targets}"

    def test_security_vars_are_forwarded(self, compose):
        """HTTPS/反代相关开关必须转发，且默认是安全的直连值（0）。"""
        env = _backend_env(compose)
        for name in ("TRUST_PROXY", "FORCE_HTTPS", "COOKIE_SECURE", "ENABLE_HSTS"):
            assert name in env, f"docker-compose.yml 未转发 {name}，文档里的 HTTPS 配置不会生效"
            assert str(env[name]).endswith(":-0}"), (
                f"{name} 的默认值必须是 0（直连安全默认）；"
                f"若默认 1，单机部署会因 COOKIE_SECURE/TRUST_PROXY 出问题"
            )

    def test_scheduler_vars_are_forwarded(self, compose):
        env = _backend_env(compose)
        for name in ("SCHEDULER_ENABLED", "SCHEDULER_INTERVAL_MINUTES"):
            assert name in env, f"docker-compose.yml 未转发 {name}"

    def test_every_app_env_var_is_accounted_for(self, compose):
        """代码读取的每个环境变量，要么被 compose 转发，要么在豁免名单里。

        这条是防「新增了环境变量但忘了同步 compose」的通用护栏。
        """
        env = _backend_env(compose)
        missing = sorted(
            _env_var_names_read_by_code()
            - set(env)
            - _COMPOSE_INTERNAL
            - _IMAGE_PROVIDED
            - _OPTIONAL
        )
        assert not missing, (
            "以下环境变量被后端代码读取，但 docker-compose.yml 没有转发，"
            f"在 Docker 部署下会静默失效: {missing}"
        )


class TestDockerfileProvidesBackupTooling:
    @staticmethod
    def _installed_packages() -> set:
        """从 Dockerfile 的 apt-get install 行解析出真正安装的包名。

        不能只在全文里搜 "postgresql-client" —— 注释里提到它也算命中，
        那样把安装删掉、只留一句注释，测试依然会通过。
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        # 跨行的 `apt-get install -y --no-install-recommends \` 续行也要接上
        text = re.sub(r"\\\s*\n\s*", " ", text)
        pkgs = set()
        for line in text.splitlines():
            if "apt-get install" not in line:
                continue
            after = line.split("apt-get install", 1)[1]
            after = after.split("&&", 1)[0]
            for token in after.split():
                if token.startswith("-") or token in ("\\", "&&"):
                    continue
                pkgs.add(token)
        return pkgs

    def test_postgresql_client_is_installed(self):
        """生产用 PostgreSQL，pg_dump 由 postgresql-client 提供。

        没有它 `_backup_postgres` 会抛 RuntimeError，自动备份永远失败。
        """
        pkgs = self._installed_packages()
        assert "postgresql-client" in pkgs, (
            f"Dockerfile 未安装 postgresql-client，容器内没有 pg_dump，"
            f"PostgreSQL 自动备份会一直失败；实际安装的包: {sorted(pkgs)}"
        )

    def test_build_verifies_pg_dump_exists(self):
        """构建期校验 pg_dump：让缺依赖在构建时失败，而不是凌晨备份时才发现。"""
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert re.search(r"^RUN\s+pg_dump\s+--version", text, re.M), (
            "Dockerfile 缺少构建期 `pg_dump --version` 校验；"
            "镜像里没有 pg_dump 时应当构建失败"
        )

    def test_pg_dump_is_installed_before_it_is_verified(self):
        """校验语句必须在安装之后，否则构建必然失败。"""
        text = DOCKERFILE.read_text(encoding="utf-8")
        install_at = text.index("postgresql-client")
        verify_at = text.index("pg_dump --version")
        assert install_at < verify_at, "pg_dump 校验出现在安装之前，构建会失败"


class TestDocsMatchDeployReality:
    def test_deployment_doc_mentions_backup_volume_requirement(self):
        """文档必须说明 Docker 下备份目录需落在卷上，否则用户会踩同一个坑。"""
        doc = (PROJECT_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        assert "backups_data" in doc, (
            "docs/deployment.md 未说明 backups_data 卷；"
            "用户可能把 BACKUP_DIR 指到卷外导致备份随容器丢失"
        )
