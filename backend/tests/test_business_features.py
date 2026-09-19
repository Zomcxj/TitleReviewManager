"""业务功能测试：跟进日程、退回统计、转化漏斗、批量下载

这四个是业务深化功能，验证数据口径与权限范围正确。
"""
import io
import zipfile
import pytest
from datetime import datetime, timedelta
from fastapi.testclient import TestClient

import models
import auth

VALID_ID = "110101199001010015"


@pytest.fixture(name="biz_salesman")
def fixture_biz_salesman(db):
    u = models.User(username="biz_s", password_hash=auth.hash_password("pass1234"),
                    role="salesman", real_name="业务甲")
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


@pytest.fixture(name="biz_data")
def fixture_biz_data(db, biz_salesman):
    """客户 + 批次 + 通过/退回材料 + 逾期跟进"""
    c = models.Customer(name="业务客户", id_number=VALID_ID, phone="13800138001",
                        assigned_salesman_id=biz_salesman.id, name_pinyin="YWKH")
    db.add(c)
    db.commit()
    a = models.Application(customer_id=c.id, professional_category="建筑工程",
                           batch_number="B-BIZ", status="提交评审机构审核",
                           submitted_at=datetime.utcnow())
    db.add(a)
    db.commit()
    m1 = models.Material(application_id=a.id, category="身份证明", filename="id.pdf",
                         file_path="x/id.pdf", file_size=10)
    m2 = models.Material(application_id=a.id, category="业绩成果", filename="ach.pdf",
                         file_path="x/ach.pdf", file_size=10)
    db.add_all([m1, m2])
    db.commit()
    db.add(models.Review(application_id=a.id, material_id=m1.id,
                         reviewer_id=biz_salesman.id, result="通过"))
    db.add(models.Review(application_id=a.id, material_id=m2.id,
                         reviewer_id=biz_salesman.id, result="退回",
                         issue_type="材料缺失", description="缺盖章"))
    db.add(models.FollowUp(customer_id=c.id, user_id=biz_salesman.id, content="首次联系",
                           follow_up_type="phone",
                           next_follow_up_at=datetime.utcnow() - timedelta(days=2)))
    db.commit()
    return c, a, m1, m2


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text


class TestFollowUpSchedule:
    def test_overdue_scope(self, client, db, biz_salesman, biz_data):
        _login(client, "biz_s", "pass1234")
        r = client.get("/api/follow-ups/schedule?scope=overdue")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] == 1
        item = data["items"][0]
        assert item["overdue"] is True
        assert item["overdue_days"] >= 1
        assert item["customer_name"] == "业务客户"

    def test_today_scope_includes_overdue(self, client, db, biz_salesman, biz_data):
        """今天的日程应包含已逾期的（都还没处理）"""
        _login(client, "biz_s", "pass1234")
        assert client.get("/api/follow-ups/schedule?scope=today").json()["total"] == 1

    def test_week_scope_excludes_overdue(self, client, db, biz_salesman, biz_data):
        """未来一周不含已过期的"""
        _login(client, "biz_s", "pass1234")
        assert client.get("/api/follow-ups/schedule?scope=week").json()["total"] == 0

    def test_invalid_scope_rejected(self, client, db, biz_salesman):
        _login(client, "biz_s", "pass1234")
        assert client.get("/api/follow-ups/schedule?scope=bad").status_code == 400

    def test_summary(self, client, db, biz_salesman, biz_data):
        _login(client, "biz_s", "pass1234")
        r = client.get("/api/follow-ups/summary")
        assert r.status_code == 200
        assert r.json()["overdue"] == 1

    def test_other_salesman_sees_nothing(self, client, db, biz_data):
        other = models.User(username="biz_o", password_hash=auth.hash_password("pass1234"),
                            role="salesman", real_name="他人")
        db.add(other)
        db.commit()
        _login(client, "biz_o", "pass1234")
        assert client.get("/api/follow-ups/schedule?scope=overdue").json()["total"] == 0

    def test_admin_sees_all(self, client, db, test_user, biz_data):
        _login(client, "testuser", "testpassword")
        assert client.get("/api/follow-ups/schedule?scope=overdue").json()["total"] == 1


class TestRejectionStats:
    def test_stats_shape_and_values(self, client, db, test_user, biz_data):
        _login(client, "testuser", "testpassword")
        r = client.get("/api/dashboard/rejection-stats?days=90")
        assert r.status_code == 200
        d = r.json()
        assert d["total_rejected"] == 1
        assert d["total_reviews"] == 2
        assert d["reject_rate"] == 50.0
        # 按类别：业绩成果被退回
        cat = {x["category"]: x for x in d["by_category"]}
        assert cat["业绩成果"]["rejected"] == 1
        assert cat["身份证明"]["rejected"] == 0
        # 按问题类型
        assert any(x["issue_type"] == "材料缺失" for x in d["by_issue_type"])
        # 按业务员
        assert any(x["salesman_id"] == biz_data[0].assigned_salesman_id for x in d["by_salesman"])
        # 趋势 30 天
        assert len(d["trend"]) == 30

    def test_salesman_scoped(self, client, db, biz_salesman, biz_data):
        _login(client, "biz_s", "pass1234")
        d = client.get("/api/dashboard/rejection-stats?days=90").json()
        assert d["total_rejected"] == 1

    def test_other_salesman_sees_zero(self, client, db, biz_data):
        other = models.User(username="biz_o2", password_hash=auth.hash_password("pass1234"),
                            role="salesman", real_name="他人")
        db.add(other)
        db.commit()
        _login(client, "biz_o2", "pass1234")
        d = client.get("/api/dashboard/rejection-stats?days=90").json()
        assert d["total_rejected"] == 0


class TestConversionFunnel:
    def test_funnel_stages(self, client, db, test_user, biz_data):
        _login(client, "testuser", "testpassword")
        r = client.get("/api/dashboard/funnel?days=180")
        assert r.status_code == 200
        d = r.json()
        assert [s["name"] for s in d["stages"]] == ["建档", "材料准备", "提交机构", "评审通过"]
        assert d["total_customers"] >= 1
        # 该客户已提交机构（submitted_at 非空）
        submitted = next(s for s in d["stages"] if s["name"] == "提交机构")
        assert submitted["count"] >= 1
        # 未通过
        approved = next(s for s in d["stages"] if s["name"] == "评审通过")
        assert approved["count"] == 0

    def test_funnel_drop_off(self, client, db, test_user, biz_data):
        _login(client, "testuser", "testpassword")
        d = client.get("/api/dashboard/funnel?days=180").json()
        assert d["drop_off"] is not None
        assert "from_stage" in d["drop_off"] and "lost" in d["drop_off"]

    def test_funnel_empty_returns_four_stages(self, client, db, test_user):
        """无客户时仍返回四阶段（前端渲染不需要特判）"""
        _login(client, "testuser", "testpassword")
        d = client.get("/api/dashboard/funnel?days=180").json()
        assert len(d["stages"]) == 4
        assert d["total_customers"] == 0

    def test_funnel_salesman_scoped(self, client, db, biz_salesman, biz_data):
        _login(client, "biz_s", "pass1234")
        d = client.get("/api/dashboard/funnel?days=180").json()
        assert d["total_customers"] == 1


class TestBatchDownload:
    def test_zip_with_real_files(self, client, db, biz_salesman):
        """用真实文件验证打包（材料写入 NAS 存储根）"""
        from storage import save_file, customer_dir
        c = models.Customer(name="Zip客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=biz_salesman.id, name_pinyin="ZIP")
        db.add(c)
        db.commit()
        a = models.Application(customer_id=c.id, professional_category="建筑工程",
                               batch_number="B-ZIP", status="初次申报")
        db.add(a)
        db.commit()
        rel = customer_dir(2026, "biz_s", "Zip客户", "ZIP")
        p1 = save_file(rel, "身份证明", "id.pdf", b"%PDF-1.4 id")
        p2 = save_file(rel, "业绩成果", "ach.pdf", b"%PDF-1.4 ach")
        db.add(models.Material(application_id=a.id, category="身份证明", filename="id.pdf",
                               file_path=p1, file_size=11))
        db.add(models.Material(application_id=a.id, category="业绩成果", filename="ach.pdf",
                               file_path=p2, file_size=12))
        db.commit()

        _login(client, "biz_s", "pass1234")
        r = client.get(f"/api/applications/{a.id}/materials/download-zip")
        assert r.status_code == 200, r.text
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        names = zf.namelist()
        assert any("身份证明" in n for n in names)
        assert len([n for n in names if n.endswith(".pdf")]) == 2
        # 内容可读
        assert b"%PDF" in zf.read([n for n in names if n.endswith(".pdf")][0])

    def test_zip_category_filter(self, client, db, biz_salesman):
        from storage import save_file, customer_dir
        c = models.Customer(name="过滤客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=biz_salesman.id, name_pinyin="GL")
        db.add(c)
        db.commit()
        a = models.Application(customer_id=c.id, batch_number="B-GL", status="初次申报")
        db.add(a)
        db.commit()
        rel = customer_dir(2026, "biz_s", "过滤客户", "GL")
        p1 = save_file(rel, "身份证明", "a.pdf", b"%PDF-1.4 a")
        p2 = save_file(rel, "业绩成果", "b.pdf", b"%PDF-1.4 b")
        db.add(models.Material(application_id=a.id, category="身份证明", filename="a.pdf",
                               file_path=p1, file_size=10))
        db.add(models.Material(application_id=a.id, category="业绩成果", filename="b.pdf",
                               file_path=p2, file_size=10))
        db.commit()
        _login(client, "biz_s", "pass1234")
        r = client.get(f"/api/applications/{a.id}/materials/download-zip?category=身份证明")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        pdfs = [n for n in zf.namelist() if n.endswith(".pdf")]
        assert len(pdfs) == 1

    def test_zip_no_materials_404(self, client, db, biz_salesman):
        c = models.Customer(name="空客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=biz_salesman.id, name_pinyin="KK")
        db.add(c)
        db.commit()
        a = models.Application(customer_id=c.id, batch_number="B-EMPTY", status="初次申报")
        db.add(a)
        db.commit()
        _login(client, "biz_s", "pass1234")
        assert client.get(f"/api/applications/{a.id}/materials/download-zip").status_code == 404

    def test_zip_other_salesman_403(self, client, db, biz_salesman):
        c = models.Customer(name="他人客户", id_number=VALID_ID, phone="13800138001",
                            assigned_salesman_id=biz_salesman.id, name_pinyin="TR")
        db.add(c)
        db.commit()
        a = models.Application(customer_id=c.id, batch_number="B-OTHER", status="初次申报")
        db.add(a)
        db.commit()
        other = models.User(username="zip_o", password_hash=auth.hash_password("pass1234"),
                            role="salesman", real_name="他人")
        db.add(other)
        db.commit()
        _login(client, "zip_o", "pass1234")
        assert client.get(f"/api/applications/{a.id}/materials/download-zip").status_code == 403
