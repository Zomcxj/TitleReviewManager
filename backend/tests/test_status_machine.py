"""Core business flow tests: state machine transitions

The state machine is central to business correctness (submitting for
institution review, approval, return, etc. all follow a strict order);
bypassing it produces severe problems like "approved before review".
"""
import pytest
from fastapi.testclient import TestClient

from enums import VALID_TRANSITIONS, ApplicationStatus

VALID_ID = "110101199001010015"


def _login(client: TestClient, username: str, password: str):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r


def _make_customer_with_app(client, db, salesman_id, status="初次申报", category="建筑工程"):
    """Create a customer + application (write the DB directly, bypassing the API's material validation)"""
    import models
    c = models.Customer(
        name="状态机客户", id_number=VALID_ID, phone="13800138001",
        assigned_salesman_id=salesman_id, name_pinyin="ZTJ",
    )
    db.add(c)
    db.commit()
    a = models.Application(
        customer_id=c.id, professional_category=category,
        batch_number=f"B-{status}-{c.id}", status=status,
    )
    db.add(a)
    db.commit()
    return c, a


def _add_all_materials(db, app_id):
    import models
    for cat in ["身份证明", "学历学位", "聘用/劳动合同", "职称证书", "业绩成果"]:
        db.add(models.Material(
            application_id=app_id, category=cat, filename=f"{cat}.pdf",
            file_path=f"t/{cat}.pdf", file_size=1,
        ))
    db.commit()


class TestStatusMachine:
    """Status transition legality"""

    def test_initial_to_supplement_allowed(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "初次申报")
        r = client.put(f"/api/applications/{app.id}", json={"status": "资料补充"})
        assert r.status_code == 200
        assert r.json()["status"] == "资料补充"

    def test_initial_to_submitted_rejected(self, client, db, test_salesman):
        """The initial-application status cannot jump straight to institution submission; it must pass through materials-complete first"""
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "初次申报")
        r = client.put(f"/api/applications/{app.id}", json={"status": "提交评审机构审核"})
        assert r.status_code == 400
        assert "不允许" in r.json()["detail"]

    def test_approved_is_terminal(self, client, db, test_user):
        """The approved status is terminal and cannot transition further"""
        _login(client, "testuser", "testpassword")
        _, app = _make_customer_with_app(client, db, test_user.id, "通过")
        r = client.put(f"/api/applications/{app.id}", json={"status": "返修"})
        assert r.status_code == 400

    def test_rejected_to_reapply(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "不通过")
        r = client.put(f"/api/applications/{app.id}", json={"status": "二次申报"})
        assert r.status_code == 200

    def test_transition_table_covers_all_statuses(self):
        """The transition table must cover every status so a newly added status cannot be missed"""
        for status in ApplicationStatus:
            assert status in VALID_TRANSITIONS, f"{status} 未在 VALID_TRANSITIONS 中定义"


class TestSubmitRequiresCompleteMaterials:
    """Submitting for institution review requires a complete material set (core business rule)"""

    def test_submit_without_materials_rejected(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "完成资料")
        r = client.post(
            f"/api/applications/{app.id}/submit-to-institution",
            json={"institution_name": "省人社厅"},
        )
        assert r.status_code == 400
        assert "缺少必传材料" in r.json()["detail"]

    def test_submit_with_materials_succeeds(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "完成资料")
        _add_all_materials(db, app.id)
        r = client.post(
            f"/api/applications/{app.id}/submit-to-institution",
            json={"institution_name": "省人社厅"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "提交评审机构审核"
        assert r.json()["cycle_year"] is not None

    def test_checklist_reports_missing(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "完成资料")
        r = client.get(f"/api/applications/{app.id}/material-checklist")
        assert r.status_code == 200
        data = r.json()
        assert data["is_complete"] is False
        assert "业绩成果" in data["missing"]

    def test_submit_requires_correct_status(self, client, db, test_salesman):
        """Cannot submit to the institution outside the materials-complete status"""
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "初次申报")
        _add_all_materials(db, app.id)
        r = client.post(
            f"/api/applications/{app.id}/submit-to-institution",
            json={"institution_name": "省厅"},
        )
        assert r.status_code == 400
        assert "完成资料" in r.json()["detail"]


class TestDuplicateApplication:
    """Duplicate application detection"""

    def test_reapply_blocked_when_active_duplicate_exists(self, client, db, test_salesman):
        import models
        _login(client, "testsalesman", "salespassword")
        c, rejected = _make_customer_with_app(client, db, test_salesman.id, "不通过")
        # The same customer/professional category/level already has an in-flight application
        db.add(models.Application(
            customer_id=c.id, professional_category="建筑工程",
            title_level=None, batch_number="B-DUP", status="完成资料",
        ))
        db.commit()
        r = client.post(f"/api/applications/{rejected.id}/reapply")
        assert r.status_code == 400
        assert "重复申报" in r.json()["detail"]

    def test_reapply_only_from_rejected(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "完成资料")
        r = client.post(f"/api/applications/{app.id}/reapply")
        assert r.status_code == 400
        assert "不通过" in r.json()["detail"]


class TestStatusRevert:
    """Status revert (correction)"""

    def test_revert_requires_admin(self, client, db, test_salesman):
        _login(client, "testsalesman", "salespassword")
        _, app = _make_customer_with_app(client, db, test_salesman.id, "提交评审机构审核")
        r = client.post(
            f"/api/applications/{app.id}/revert-status",
            json={"target_status": "完成资料", "reason": "误提交"},
        )
        assert r.status_code == 403

    def test_revert_requires_reason(self, client, db, test_user):
        _login(client, "testuser", "testpassword")
        _, app = _make_customer_with_app(client, db, test_user.id, "提交评审机构审核")
        r = client.post(
            f"/api/applications/{app.id}/revert-status",
            json={"target_status": "完成资料"},
        )
        assert r.status_code == 400
        assert "原因" in r.json()["detail"]

    def test_revert_success_clears_institution(self, client, db, test_user):
        import models
        _login(client, "testuser", "testpassword")
        _, app = _make_customer_with_app(client, db, test_user.id, "提交评审机构审核")
        app.institution_name = "省厅"
        db.commit()
        r = client.post(
            f"/api/applications/{app.id}/revert-status",
            json={"target_status": "完成资料", "reason": "误提交"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "完成资料"
        # Reverting to the pre-submission status should clear the institution field
        assert r.json()["institution_name"] is None

    def test_revert_to_invalid_target_rejected(self, client, db, test_user):
        _login(client, "testuser", "testpassword")
        _, app = _make_customer_with_app(client, db, test_user.id, "提交评审机构审核")
        r = client.post(
            f"/api/applications/{app.id}/revert-status",
            json={"target_status": "通过", "reason": "测试"},
        )
        assert r.status_code == 400
