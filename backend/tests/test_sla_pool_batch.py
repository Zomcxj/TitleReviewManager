"""SLA 定时任务、公海池与批量操作测试

覆盖：SLA 自动回收（此前因 or_ 未导入而从未生效）、软删除过滤、
批量操作条数上限与频率限制。
"""
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

import models
import auth

VALID_ID = "110101199001010015"


@pytest.fixture(name="pool_salesman")
def fixture_pool_salesman(db):
    u = models.User(username="pool_s", password_hash=auth.hash_password("pass1234"),
                    role="salesman", real_name="公海业务")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


class TestSlaRecovery:
    """SLA 自动回收（sla_scheduler）"""

    def test_never_followed_new_customer_not_recovered(self, db, pool_salesman):
        """新建但从未跟进的客户不应被立刻回收（此前会误伤）"""
        from tasks.sla_scheduler import check_and_recovery_customers
        c = models.Customer(name="新客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=pool_salesman.id, name_pinyin="XKH",
                            last_follow_up_at=None)
        db.add(c)
        db.commit()
        check_and_recovery_customers()
        db.refresh(c)
        assert c.is_public is False, "新建客户不应被回收"

    def test_long_untouched_customer_recovered(self, db, pool_salesman):
        """超过回收天数未跟进的客户应被回收"""
        from tasks.sla_scheduler import check_and_recovery_customers, POOL_RECOVERY_DAYS
        old = datetime.utcnow() - timedelta(days=POOL_RECOVERY_DAYS + 3)
        c = models.Customer(name="久未跟进", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=pool_salesman.id, name_pinyin="JW",
                            last_follow_up_at=old, created_at=old)
        db.add(c)
        db.commit()
        check_and_recovery_customers()
        db.refresh(c)
        assert c.is_public is True
        assert c.assigned_salesman_id is None

    def test_soft_deleted_customer_skipped(self, db, pool_salesman):
        """已软删除的客户不应被 SLA 任务处理"""
        from tasks.sla_scheduler import check_and_recovery_customers, POOL_RECOVERY_DAYS
        old = datetime.utcnow() - timedelta(days=POOL_RECOVERY_DAYS + 3)
        c = models.Customer(name="已删除", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=pool_salesman.id, name_pinyin="YSC",
                            last_follow_up_at=old, created_at=old, is_deleted=True)
        db.add(c)
        db.commit()
        check_and_recovery_customers()
        db.refresh(c)
        assert c.is_public is False, "软删除客户不应被 SLA 任务改动"

    def test_sla_deadline_cleared_after_notify(self, db, pool_salesman):
        """SLA 超时通知后应清除 deadline，避免每次运行重复轰炸"""
        from tasks.sla_scheduler import check_sla_deadlines
        c = models.Customer(name="超时客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=pool_salesman.id, name_pinyin="CS",
                            sla_deadline=datetime.utcnow() - timedelta(hours=1))
        db.add(c)
        db.commit()
        check_sla_deadlines()
        db.refresh(c)
        assert c.sla_deadline is None, "通知后应清除 deadline 防重复"


class TestPublicPool:
    def test_claim_respects_limit(self, client, db, pool_salesman):
        """领取公海客户受持有上限约束"""
        from utils.system_config import set_config, invalidate_cache
        set_config(db, "pool_claim_limit", 1)
        invalidate_cache()
        # 已有 1 个非公海客户
        db.add(models.Customer(name="已有", id_number=VALID_ID, phone="13800138001",
                               assigned_salesman_id=pool_salesman.id, name_pinyin="YY",
                               is_public=False))
        # 公海里 1 个
        p = models.Customer(name="公海", id_number="110101199001010023", phone="13800138002",
                            name_pinyin="GH", is_public=True, public_at=datetime.utcnow())
        db.add(p)
        db.commit()
        _login(client, "pool_s", "pass1234")
        r = client.post(f"/api/public-pool/claim/{p.id}")
        assert r.status_code == 400
        assert "最多持有" in r.json()["detail"]

    def test_claim_sets_sla_deadline(self, client, db, pool_salesman):
        from utils.system_config import set_config, invalidate_cache
        set_config(db, "pool_claim_limit", 50)
        invalidate_cache()
        p = models.Customer(name="可领", id_number=VALID_ID, phone="13800138001",
                            name_pinyin="KL", is_public=True, public_at=datetime.utcnow())
        db.add(p)
        db.commit()
        _login(client, "pool_s", "pass1234")
        r = client.post(f"/api/public-pool/claim/{p.id}")
        assert r.status_code == 200
        db.refresh(p)
        assert p.sla_deadline is not None
        assert p.is_public is False

    def test_release_others_customer_rejected(self, client, db, pool_salesman):
        other = models.User(username="pool_o", password_hash=auth.hash_password("pass1234"),
                            role="salesman", real_name="他人")
        db.add(other)
        db.commit()
        c = models.Customer(name="他人客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=pool_salesman.id, name_pinyin="T R".replace(" ", ""))
        db.add(c)
        db.commit()
        _login(client, "pool_o", "pass1234")
        r = client.post(f"/api/public-pool/release/{c.id}")
        assert r.status_code == 403


class TestBatchGuards:
    def test_batch_size_limit(self, client, db, test_user, pool_salesman):
        _login(client, "testuser", "testpassword")
        r = client.post("/api/batch/assign-customers",
                        json={"customer_ids": list(range(1, 400)), "salesman_id": pool_salesman.id})
        assert r.status_code == 400
        assert "最多" in r.json()["detail"]

    def test_batch_empty_rejected(self, client, db, test_user, pool_salesman):
        _login(client, "testuser", "testpassword")
        r = client.post("/api/batch/assign-customers",
                        json={"customer_ids": [], "salesman_id": pool_salesman.id})
        assert r.status_code == 400

    def test_batch_assign_sets_sla_not_expired(self, client, db, test_user, pool_salesman):
        """批量分配应设置 24h 后的 SLA，而不是"立刻逾期" """
        c = models.Customer(name="批量", id_number=VALID_ID, phone="13800138001", name_pinyin="PL")
        db.add(c)
        db.commit()
        _login(client, "testuser", "testpassword")
        r = client.post("/api/batch/assign-customers",
                        json={"customer_ids": [c.id], "salesman_id": pool_salesman.id})
        assert r.status_code == 200
        db.refresh(c)
        assert c.sla_deadline > datetime.utcnow(), "SLA 截止时间应在未来"

    def test_batch_requires_admin(self, client, db, test_salesman, pool_salesman):
        _login(client, "testsalesman", "salespassword")
        r = client.post("/api/batch/assign-customers",
                        json={"customer_ids": [1], "salesman_id": pool_salesman.id})
        assert r.status_code == 403


class TestRecycleBin:
    def test_soft_delete_excludes_from_list(self, client, db, test_user):
        c = models.Customer(name="待删", id_number=VALID_ID, phone="13800138001", name_pinyin="DS")
        db.add(c)
        db.commit()
        cid = c.id
        _login(client, "testuser", "testpassword")
        r = client.delete(f"/api/customers/{cid}")
        assert r.status_code == 200
        ids = [x["id"] for x in client.get("/api/customers/").json()["items"]]
        assert cid not in ids
        # 回收站可见
        names = [(x["resource_type"], x["id"]) for x in client.get("/api/recycle-bin/").json()["items"]]
        assert ("customer", cid) in names
        # 恢复
        assert client.post("/api/recycle-bin/restore",
                           json={"resource_type": "customer", "id": cid}).status_code == 200
        ids = [x["id"] for x in client.get("/api/customers/").json()["items"]]
        assert cid in ids

    def test_delete_blocked_for_reviewing_customer(self, client, db, test_user):
        """有评审中批次的客户不能删除"""
        c = models.Customer(name="评审中", id_number=VALID_ID, phone="13800138001", name_pinyin="PSZ")
        db.add(c)
        db.commit()
        db.add(models.Application(customer_id=c.id, batch_number="B-PSZ", status="提交评审机构审核"))
        db.commit()
        _login(client, "testuser", "testpassword")
        r = client.delete(f"/api/customers/{c.id}")
        assert r.status_code == 400
        assert "评审中" in r.json()["detail"]

    def test_recycle_bin_requires_admin(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        assert client.get("/api/recycle-bin/").status_code == 403


class TestSystemConfig:
    def test_config_change_takes_effect(self, client, db, test_user):
        _login(client, "testuser", "testpassword")
        r = client.put("/api/system-config/", json={"pool_claim_limit": 77})
        assert r.status_code == 200
        assert client.get("/api/system-config/").json()["pool_claim_limit"]["value"] == 77

    def test_config_reset(self, client, db, test_user):
        _login(client, "testuser", "testpassword")
        client.put("/api/system-config/", json={"pool_claim_limit": 99})
        r = client.post("/api/system-config/reset")
        body = r.json()
        cfg = body.get("configs", body)
        assert cfg["pool_claim_limit"]["value"] == 50

    def test_config_requires_admin(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        assert client.get("/api/system-config/").status_code == 403
