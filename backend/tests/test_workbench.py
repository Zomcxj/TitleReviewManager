"""今日待办工作台测试

待办接口将散落的跟进、审核、截止、回款汇总成按角色过滤的 dashboard，
并验证调度器能否正确触发三类运营催办通知。
"""
import pytest
from fastapi.testclient import TestClient
from datetime import datetime, timedelta


VALID_ID = "110101199001010015"


def _login(client: TestClient, username: str, password: str):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def _make_customer(db, salesman_id, name="待办客户"):
    import models
    c = models.Customer(
        name=name, id_number=VALID_ID, phone="13800138002",
        assigned_salesman_id=salesman_id, name_pinyin="DB",
    )
    db.add(c)
    db.commit()
    db.refresh(c)
    return c


def _make_app(db, customer_id, status="完成资料", batch="WBBATCH"):
    import models
    a = models.Application(
        customer_id=customer_id, professional_category="建筑工程",
        batch_number=batch, status=status,
    )
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


class TestWorkbench:
    """今日待办工作台"""

    def test_workbench_returns_summary(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert "summary" in data
        assert "follow_ups" in data
        assert "reviews" in data
        assert "deadlines" in data
        assert "payments" in data
        assert data["role"] == "salesman"

    def test_workbench_overdue_follow_ups(self, client, db, test_salesman):
        import models
        c = _make_customer(db, test_salesman.id, "逾期跟进客户")
        overdue = datetime.utcnow() - timedelta(days=2)
        db.add(models.FollowUp(
            customer_id=c.id, user_id=test_salesman.id,
            next_follow_up_at=overdue, content="测试跟进",
        ))
        db.commit()
        _login(client, "testsalesman", "salespassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["follow_ups_overdue"] >= 1
        assert any(item["customer_id"] == c.id for item in data["follow_ups"])

    def test_workbench_pending_reviews(self, client, db, test_salesman):
        import models
        c = _make_customer(db, test_salesman.id, "待审客户")
        app = _make_app(db, c.id, "完成资料", "WBPEND")
        db.add(models.Material(
            application_id=app.id, category="身份证明",
            filename="id.pdf", file_path="t/id.pdf", file_size=1,
            audit_status="待审核",
        ))
        db.commit()
        _login(client, "testsalesman", "salespassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["pending_reviews"] >= 1
        assert any(item["application_id"] == app.id for item in data["reviews"])

    def test_workbench_upcoming_deadlines(self, client, db, test_salesman):
        import models
        c = _make_customer(db, test_salesman.id, "截止客户")
        soon = datetime.utcnow() + timedelta(days=3)
        app = _make_app(db, c.id, "完成资料", "WBDEAD")
        app.cycle_deadline = soon
        db.commit()
        _login(client, "testsalesman", "salespassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["upcoming_deadlines"] >= 1
        assert any(item["application_id"] == app.id for item in data["deadlines"])

    def test_workbench_pending_payments(self, client, db, test_salesman):
        import models
        c = _make_customer(db, test_salesman.id, "欠款客户")
        app = _make_app(db, c.id, "通过", "WBPAY")
        app.fee_amount = 5000.0
        app.paid_amount = 1000.0
        db.commit()
        _login(client, "testsalesman", "salespassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["summary"]["pending_payments"] >= 1
        assert any(item["application_id"] == app.id for item in data["payments"])

    def test_reviewer_no_payments(self, client, db, test_user):
        test_user.role = "reviewer"
        db.commit()
        _login(client, "testuser", "testpassword")
        r = client.get("/api/dashboard/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["role"] == "reviewer"
        assert data["summary"]["pending_payments"] == 0
        assert len(data["payments"]) == 0


class TestReviewQueue:
    """审核队列后端化"""

    def test_pending_reviews_empty(self, client, db, test_user):
        _login(client, "testuser", "testpassword")
        r = client.get("/api/reviews/pending")
        assert r.status_code == 200
        data = r.json()
        assert "items" in data
        assert "total" in data

    def test_pending_reviews_filters_by_status(self, client, db, test_salesman, test_user):
        import models
        c = _make_customer(db, test_salesman.id, "状态过滤客户")
        app = _make_app(db, c.id, "资料补充", "FILT")
        db.add(models.Material(
            application_id=app.id, category="身份证明",
            filename="f.pdf", file_path="t/f.pdf", file_size=1,
            audit_status="待审核",
        ))
        db.commit()
        _login(client, "testuser", "testpassword")
        r = client.get("/api/reviews/pending", params={"status": "资料补充"})
        assert r.status_code == 200
        data = r.json()
        assert any(item["status"] == "资料补充" for item in data["items"])

    def test_pending_reviews_only_with_materials(self, client, db, test_salesman, test_user):
        """队列只显示仍有待审材料的批次，材料已全审完的批次不出现"""
        import models
        c = _make_customer(db, test_salesman.id, "材料已审完")
        app = _make_app(db, c.id, "完成资料", "ALLAP")
        db.add(models.Material(
            application_id=app.id, category="身份证明",
            filename="ap.pdf", file_path="t/ap.pdf", file_size=1,
            audit_status="已通过",
        ))
        db.commit()
        _login(client, "testuser", "testpassword")
        r = client.get("/api/reviews/pending")
        assert r.status_code == 200
        data = r.json()
        assert not any(item["application_id"] == app.id for item in data["items"])


class TestReminders:
    """运营催办（跟进逾期、审核 SLA、申报截止）"""

    def test_review_sla_skip_no_pending_materials(self, client, db, test_salesman):
        """材料已全审完不再催办审核 SLA"""
        import models
        c = _make_customer(db, test_salesman.id, "材料已全审")
        app = _make_app(db, c.id, "完成资料", "NOSLA")
        app.review_sla_deadline = datetime.utcnow() - timedelta(hours=5)
        db.add(models.Material(
            application_id=app.id, category="身份证明",
            filename="done.pdf", file_path="t/done.pdf", file_size=1,
            audit_status="已通过",
        ))
        db.commit()
        before = db.query(models.Notification).count()
        from utils.reminders import send_review_sla_reminders
        send_review_sla_reminders(db)
        after = db.query(models.Notification).count()
        # 不应产生新通知，因为该批次没有待审核材料
        assert after == before

    def test_scheduler_calls_all_reminders(self, client, db, test_salesman):
        """调度器集成：一轮触发全部催办"""
        from utils.reminders import send_operational_reminders
        result = send_operational_reminders()
        assert "follow_up" in result
        assert "review_sla" in result
        assert "cycle_deadline" in result
