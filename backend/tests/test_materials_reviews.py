"""材料管理与审核流程测试

覆盖：上传校验（扩展名/大小/内容魔数）、版本号、审核权限与状态联动。
"""
import io
import pytest
from fastapi.testclient import TestClient

import models
import auth

VALID_ID = "110101199001010015"
PDF_BYTES = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"
HTML_BYTES = b"<html><body><script>alert(1)</script></body></html>"


@pytest.fixture(name="owner_app")
def fixture_owner_app(db, test_salesman):
    """业务员名下的客户 + 批次"""
    c = models.Customer(name="材料客户", id_number=VALID_ID, phone="13800138001",
                        assigned_salesman_id=test_salesman.id, name_pinyin="CLKH")
    db.add(c)
    db.commit()
    a = models.Application(customer_id=c.id, professional_category="建筑工程",
                           batch_number="B-MAT", status="初次申报")
    db.add(a)
    db.commit()
    return c, a


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


def _upload(client, app_id, category, filename, content, content_type="application/pdf"):
    return client.post(
        f"/api/applications/{app_id}/materials/",
        data={"category": category},
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


class TestUploadValidation:
    def test_valid_pdf_accepted(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r = _upload(client, app.id, "身份证明", "id.pdf", PDF_BYTES)
        assert r.status_code == 200, r.text

    def test_disallowed_extension_rejected(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r = _upload(client, app.id, "身份证明", "evil.exe", b"MZ\x90\x00")
        assert r.status_code == 400
        assert "不支持的文件类型" in r.json()["detail"]

    def test_fake_pdf_rejected_by_magic_bytes(self, client, db, test_salesman, owner_app):
        """改扩展名伪装的文件必须被内容校验拦住"""
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r = _upload(client, app.id, "身份证明", "fake.pdf", HTML_BYTES)
        assert r.status_code == 400
        assert "不符" in r.json()["detail"]

    def test_invalid_category_rejected(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r = _upload(client, app.id, "不存在的类别", "x.pdf", PDF_BYTES)
        assert r.status_code == 400

    def test_reviewer_cannot_upload(self, client, db, test_reviewer, owner_app):
        _login(client, "testreviewer", "reviewpassword")
        _, app = owner_app
        r = _upload(client, app.id, "身份证明", "x.pdf", PDF_BYTES)
        assert r.status_code == 403

    def test_other_salesman_cannot_upload(self, client, db, owner_app):
        other = models.User(username="other_s", password_hash=auth.hash_password("pass1234"),
                            role="salesman", real_name="其他业务")
        db.add(other)
        db.commit()
        _login(client, "other_s", "pass1234")
        _, app = owner_app
        r = _upload(client, app.id, "身份证明", "x.pdf", PDF_BYTES)
        assert r.status_code == 403


class TestMaterialVersioning:
    def test_version_increments_per_category(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r1 = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES)
        r2 = _upload(client, app.id, "身份证明", "b.pdf", PDF_BYTES)
        assert r1.json()["version"] == 1
        assert r2.json()["version"] == 2

    def test_version_independent_across_categories(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r1 = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES)
        r2 = _upload(client, app.id, "学历学位", "b.pdf", PDF_BYTES)
        assert r1.json()["version"] == 1
        assert r2.json()["version"] == 1


class TestMaterialAuditStatus:
    def test_salesman_cannot_change_audit_status(self, client, db, test_salesman, owner_app):
        """业务员不能自己把材料标为已通过（关键越权）"""
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        r = client.put(f"/api/applications/{app.id}/materials/{mid}",
                       data={"audit_status": "已通过"})
        assert r.status_code == 403

    def test_salesman_can_change_remark(self, client, db, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        r = client.put(f"/api/applications/{app.id}/materials/{mid}",
                       data={"remark": "补充说明"})
        assert r.status_code == 200
        assert r.json()["remark"] == "补充说明"

    def test_reviewer_can_change_audit_status(self, client, db, test_reviewer, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        client.post("/api/auth/logout")
        _login(client, "testreviewer", "reviewpassword")
        r = client.put(f"/api/applications/{app.id}/materials/{mid}",
                       data={"audit_status": "已通过"})
        assert r.status_code == 200
        assert r.json()["audit_status"] == "已通过"

    def test_invalid_audit_status_rejected(self, client, db, test_reviewer, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        client.post("/api/auth/logout")
        _login(client, "testreviewer", "reviewpassword")
        r = client.put(f"/api/applications/{app.id}/materials/{mid}",
                       data={"audit_status": "随便写的状态"})
        assert r.status_code == 400


class TestReviewCreation:
    def test_salesman_cannot_review(self, client, db, test_salesman, owner_app):
        """业务员不能审核自己客户的材料（关键越权）"""
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        r = client.post("/api/reviews/", data={
            "material_id": mid, "application_id": app.id, "result": "通过",
        })
        assert r.status_code == 403

    def test_reviewer_can_review(self, client, db, test_reviewer, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        client.post("/api/auth/logout")
        _login(client, "testreviewer", "reviewpassword")
        r = client.post("/api/reviews/", data={
            "material_id": mid, "application_id": app.id,
            "result": "通过", "description": "材料齐全",
        })
        assert r.status_code == 200, r.text

    def test_invalid_result_rejected(self, client, db, test_reviewer, test_salesman, owner_app):
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        mid = _upload(client, app.id, "身份证明", "a.pdf", PDF_BYTES).json()["id"]
        client.post("/api/auth/logout")
        _login(client, "testreviewer", "reviewpassword")
        r = client.post("/api/reviews/", data={
            "material_id": mid, "application_id": app.id, "result": "随便",
        })
        assert r.status_code == 400


class TestFeedbackStateMachine:
    def test_feedback_requires_reviewer_role(self, client, db, test_salesman, owner_app):
        """业务员不能录入机构反馈（否则可自行让批次通过）"""
        _login(client, "testsalesman", "salespassword")
        _, app = owner_app
        r = client.post("/api/feedback/", data={
            "application_id": app.id, "feedback_type": "通过", "content": "自批通过",
        })
        assert r.status_code == 403

    def test_feedback_requires_correct_status(self, client, db, test_reviewer, owner_app):
        """只有"提交评审机构审核"状态才能录入机构反馈"""
        _login(client, "testreviewer", "reviewpassword")
        _, app = owner_app  # 状态为 初次申报
        r = client.post("/api/feedback/", data={
            "application_id": app.id, "feedback_type": "通过", "content": "x",
        })
        assert r.status_code == 400
        assert "不允许" in r.json()["detail"]

    def test_feedback_drives_status_when_allowed(self, client, db, test_reviewer, owner_app):
        _login(client, "testreviewer", "reviewpassword")
        _, app = owner_app
        app.status = "提交评审机构审核"
        db.commit()
        r = client.post("/api/feedback/", data={
            "application_id": app.id, "feedback_type": "通过", "content": "恭喜通过",
        })
        assert r.status_code == 200
        db.refresh(app)
        assert app.status == "通过"

    def test_invalid_feedback_type_rejected(self, client, db, test_reviewer, owner_app):
        _login(client, "testreviewer", "reviewpassword")
        _, app = owner_app
        app.status = "提交评审机构审核"
        db.commit()
        r = client.post("/api/feedback/", data={
            "application_id": app.id, "feedback_type": "乱写", "content": "x",
        })
        assert r.status_code == 400
