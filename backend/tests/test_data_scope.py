"""权限与数据隔离测试

覆盖：业务员只能访问自己名下客户的数据（审核记录/机构反馈/跟进/财务/材料清单），
审核员可跨业务员（工作需要），管理员不受限。
"""
import pytest
from fastapi.testclient import TestClient

import models
import auth

VALID_ID_A = "110101199001010015"
VALID_ID_B = "110101199001010023"


@pytest.fixture(name="two_salesmen")
def fixture_two_salesmen(db):
    s1 = models.User(username="sales_a", password_hash=auth.hash_password("pass1234"), role="salesman", real_name="业务A")
    s2 = models.User(username="sales_b", password_hash=auth.hash_password("pass1234"), role="salesman", real_name="业务B")
    db.add_all([s1, s2])
    db.commit()
    db.refresh(s1)
    db.refresh(s2)
    return s1, s2


@pytest.fixture(name="b_customer_app")
def fixture_b_customer_app(db, two_salesmen):
    """业务B 名下的客户与批次（含材料、审核、反馈、跟进）"""
    _, s2 = two_salesmen
    c = models.Customer(name="B的客户", id_number=VALID_ID_B, phone="13800138002",
                        assigned_salesman_id=s2.id, name_pinyin="BDKH")
    db.add(c)
    db.commit()
    a = models.Application(customer_id=c.id, professional_category="建筑工程",
                           batch_number="B-BCUST", status="返修")
    db.add(a)
    db.commit()
    m = models.Material(application_id=a.id, category="身份证明", filename="x.pdf",
                        file_path="p/x.pdf", file_size=1)
    db.add(m)
    db.commit()
    db.add(models.Review(application_id=a.id, material_id=m.id, reviewer_id=s2.id,
                         result="退回", issue_type="材料缺失", description="缺合同"))
    db.add(models.Feedback(application_id=a.id, feedback_type="返修", content="机构意见"))
    db.add(models.FollowUp(customer_id=c.id, user_id=s2.id, content="已联系", follow_up_type="phone"))
    db.commit()
    return c, a, m


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


class TestSalesmanCannotAccessOthersData:
    """业务员访问他人客户数据必须 403"""

    def test_cannot_read_others_customer_detail(self, client, db, two_salesmen, b_customer_app):
        s1, _ = two_salesmen
        c, _, _ = b_customer_app
        _login(client, "sales_a", "pass1234")
        assert client.get(f"/api/customers/{c.id}").status_code == 403

    def test_cannot_read_others_application(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        _, a, _ = b_customer_app
        assert client.get(f"/api/applications/{a.id}").status_code == 403

    def test_cannot_read_others_reviews(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        _, a, m = b_customer_app
        assert client.get(f"/api/reviews/application/{a.id}").status_code == 403
        assert client.get(f"/api/reviews/material/{m.id}").status_code == 403

    def test_cannot_read_others_feedback(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        _, a, _ = b_customer_app
        assert client.get(f"/api/feedback/application/{a.id}").status_code == 403
        assert client.get(f"/api/feedback/application/{a.id}/logs").status_code == 403

    def test_cannot_read_others_follow_ups(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        c, _, _ = b_customer_app
        assert client.get(f"/api/follow-ups/customer/{c.id}").status_code == 403

    def test_cannot_read_others_finance(self, client, db, two_salesmen, b_customer_app):
        """财务数据（合同金额、回款）属敏感经营数据"""
        _login(client, "sales_a", "pass1234")
        _, a, _ = b_customer_app
        assert client.get(f"/api/finance/application/{a.id}").status_code == 403

    def test_cannot_read_others_material_checklist(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        _, a, _ = b_customer_app
        assert client.get(f"/api/applications/{a.id}/material-checklist").status_code == 403

    def test_cannot_download_others_material(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_a", "pass1234")
        _, a, m = b_customer_app
        assert client.get(f"/api/applications/{a.id}/materials/file/{m.id}").status_code == 403


class TestOwnerCanAccessOwnData:
    """数据归属人可正常访问"""

    def test_owner_can_read_all(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_b", "pass1234")
        c, a, m = b_customer_app
        assert client.get(f"/api/customers/{c.id}").status_code == 200
        assert client.get(f"/api/applications/{a.id}").status_code == 200
        assert client.get(f"/api/reviews/application/{a.id}").status_code == 200
        assert client.get(f"/api/feedback/application/{a.id}").status_code == 200
        assert client.get(f"/api/follow-ups/customer/{c.id}").status_code == 200
        assert client.get(f"/api/finance/application/{a.id}").status_code == 200
        assert client.get(f"/api/applications/{a.id}/material-checklist").status_code == 200


class TestReviewerCrossSalesman:
    """审核员需要跨业务员查看（工作职责）"""

    def test_reviewer_can_read_any(self, client, db, test_reviewer, b_customer_app):
        _login(client, "testreviewer", "reviewpassword")
        c, a, m = b_customer_app
        assert client.get(f"/api/customers/{c.id}").status_code == 200
        assert client.get(f"/api/reviews/application/{a.id}").status_code == 200
        assert client.get(f"/api/feedback/application/{a.id}").status_code == 200
        assert client.get(f"/api/applications/{a.id}/material-checklist").status_code == 200

    def test_reviewer_cannot_modify_customer(self, client, db, test_reviewer, b_customer_app):
        """审核员可读但不可改客户"""
        _login(client, "testreviewer", "reviewpassword")
        c, _, _ = b_customer_app
        r = client.put(f"/api/customers/{c.id}", json={"phone": "13900139000"})
        assert r.status_code == 403

    def test_reviewer_cannot_create_customer(self, client, db, test_reviewer):
        _login(client, "testreviewer", "reviewpassword")
        r = client.post("/api/customers/", json={"name": "X", "id_number": VALID_ID_A})
        assert r.status_code == 403

    def test_reviewer_cannot_export(self, client, db, test_reviewer):
        _login(client, "testreviewer", "reviewpassword")
        assert client.post("/api/exports/customers").status_code == 403


class TestAdminUnrestricted:
    def test_admin_can_read_any(self, client, db, test_user, b_customer_app):
        _login(client, "testuser", "testpassword")
        c, a, _ = b_customer_app
        assert client.get(f"/api/customers/{c.id}").status_code == 200
        assert client.get(f"/api/finance/application/{a.id}").status_code == 200


class TestSensitiveFieldMasking:
    """字段级脱敏：审核员看客户证件号应脱敏"""

    def test_reviewer_sees_masked_id(self, client, db, test_reviewer, b_customer_app):
        _login(client, "testreviewer", "reviewpassword")
        c, _, _ = b_customer_app
        r = client.get(f"/api/customers/{c.id}")
        assert r.status_code == 200
        assert "*" in r.json()["id_number"], "审核员看到的证件号应脱敏"

    def test_admin_sees_full_id(self, client, db, test_user, b_customer_app):
        _login(client, "testuser", "testpassword")
        c, _, _ = b_customer_app
        r = client.get(f"/api/customers/{c.id}")
        assert r.json()["id_number"] == VALID_ID_B

    def test_owner_sees_full_id(self, client, db, two_salesmen, b_customer_app):
        _login(client, "sales_b", "pass1234")
        c, _, _ = b_customer_app
        r = client.get(f"/api/customers/{c.id}")
        assert r.json()["id_number"] == VALID_ID_B
