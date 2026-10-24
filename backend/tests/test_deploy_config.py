"""Deployment config consistency: docker-compose.yml / Dockerfile must actually pass config into the container.

Background (real defects fixed here):
- `Dockerfile` installed only `libpq5`, not `postgresql-client` → no `pg_dump`
  in the container → automatic backup under PostgreSQL always fails
  (it would only send one in-app notification at 3 a.m.).
- `docker-compose.yml` does not use `env_file`; variables in `.env` only take
  effect if listed one by one in the `environment` section, and things like
  `BACKUP_*` / `TRUST_PROXY` were not listed at all
  → the backup directory, retention count, and HTTPS switches users carefully
  configured in `.env` were all silently ignored.
- No volume mounts the backup directory → it defaults to `/app/backups` and
  is lost whenever the container is rebuilt.

The common trait of these defects is "config looks set but does not actually
take effect", and they only surface in production, so tests align the
"environment variables the code reads" with "the environment variables
compose forwards".
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
    """Scan backend source and collect every environment variable name that gets read.

    Covers both styles:
    - os.getenv("NAME") / os.environ["NAME"] / os.environ.get("NAME")
    - project helper functions like _env_flag("NAME", ...) (called with literal arguments)
    """
    names = set()
    patterns = [
        re.compile(r'os\.getenv\(\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(r'os\.environ(?:\.get)?[\(\[]\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(r'_env_flag\(\s*"([A-Z][A-Z0-9_]*)"'),
        re.compile(r'_env_int\(\s*"([A-Z][A-Z0-9_]*)"'),
    ]
    for py in BACKEND_DIR.rglob("*.py"):
        # The tests themselves do not count as deployment-config readers
        if "tests" in py.parts or "__pycache__" in py.parts:
            continue
        text = py.read_text(encoding="utf-8", errors="ignore")
        for pat in patterns:
            names.update(pat.findall(text))
    return names


# These variables are consumed by compose itself (not passed to the app container)
# or provided by the base image / runtime; they should not be required to appear
# in the backend service's environment.
_COMPOSE_INTERNAL = {
    "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB", "APP_PORT",
}
_IMAGE_PROVIDED = {
    "FRONTEND_DIST", "PYTHONUNBUFFERED", "PYTHONDONTWRITEBYTECODE",
    "PATH", "HOME", "HOSTNAME",
}
# Only needed for specific deployment styles, and their defaults are already the
# correct safe defaults (standalone direct connection). They should still be
# forwarded, but their absence from compose must not error — see
# test_security_vars_forwarded below.
_OPTIONAL = {"APP_VERSION", "SCHEDULER_STARTUP_DELAY"}


class TestComposeForwardsAppConfig:
    def test_backup_vars_are_forwarded(self, compose):
        """Backup-related variables must be forwarded: otherwise every .env setting is ignored.

        This is the most damaging class — the user believes BACKUP_DIR/BACKUP_KEEP
        is set while the app is still using defaults, with no error at all.
        """
        env = _backend_env(compose)
        for name in (
            "BACKUP_ENABLED", "BACKUP_DIR", "BACKUP_KEEP", "BACKUP_HOUR",
            "BACKUP_INCLUDE_FILES", "BACKUP_COMPRESS", "BACKUP_DRILL_ENABLED",
        ):
            assert name in env, f"docker-compose.yml 未转发 {name}，.env 中的设置不会生效"

    def test_backup_dir_points_into_a_mounted_volume(self, compose):
        """The backup directory must live inside a mounted volume, otherwise backups vanish when the container is rebuilt."""
        env = _backend_env(compose)
        # Form like ${BACKUP_DIR:-/data/backups} — extract the default value
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
        """HTTPS/reverse-proxy switches must be forwarded, defaulting to the safe direct-connection value (0)."""
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
        """Every environment variable the code reads must be either forwarded by compose or on the exemption list.

        This is the general guardrail against "added an env var but forgot to sync compose".
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
        """Parse the actually installed package names from the Dockerfile's apt-get install lines.

        Searching the whole file for "postgresql-client" is not enough — a mention
        in a comment would also match, so deleting the install and leaving one
        comment behind would still pass.
        """
        text = DOCKERFILE.read_text(encoding="utf-8")
        # Continuation lines of a multi-line `apt-get install -y --no-install-recommends \` must be joined too
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
        """Production uses PostgreSQL; pg_dump is provided by postgresql-client.

        Without it `_backup_postgres` raises RuntimeError and automatic backup always fails.
        """
        pkgs = self._installed_packages()
        assert "postgresql-client" in pkgs, (
            f"Dockerfile 未安装 postgresql-client，容器内没有 pg_dump，"
            f"PostgreSQL 自动备份会一直失败；实际安装的包: {sorted(pkgs)}"
        )

    def test_build_verifies_pg_dump_exists(self):
        """Build-time pg_dump check: a missing dependency fails the build instead of being discovered during a 3 a.m. backup."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        assert re.search(r"^RUN\s+pg_dump\s+--version", text, re.M), (
            "Dockerfile 缺少构建期 `pg_dump --version` 校验；"
            "镜像里没有 pg_dump 时应当构建失败"
        )

    def test_pg_dump_is_installed_before_it_is_verified(self):
        """The check must come after the install, otherwise the build always fails."""
        text = DOCKERFILE.read_text(encoding="utf-8")
        install_at = text.index("postgresql-client")
        verify_at = text.index("pg_dump --version")
        assert install_at < verify_at, "pg_dump 校验出现在安装之前，构建会失败"


class TestDocsMatchDeployReality:
    def test_deployment_doc_mentions_backup_volume_requirement(self):
        """The docs must state that under Docker the backup directory must live on a volume, otherwise users hit the same pit."""
        doc = (PROJECT_ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")
        assert "backups_data" in doc, (
            "docs/deployment.md 未说明 backups_data 卷；"
            "用户可能把 BACKUP_DIR 指到卷外导致备份随容器丢失"
        )
