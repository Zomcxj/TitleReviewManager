from database import SessionLocal, Base, engine
import models  # noqa: F401 - needed for table registration
from models import User, Customer, Application, Material, Review, Feedback, OperationLog
from auth import hash_password
from storage import customer_dir, get_pinyin_initial, save_file
import uuid
from datetime import datetime, timedelta
from sqlalchemy import text

# 注意：数据库结构迁移现在由 Alembic 管理。
# 请运行 alembic upgrade head 来更新数据库结构。
# 本脚本仅用于填充种子数据。

DEFAULT_USERS = [
    {"username": "admin", "password": "admin123", "role": "admin", "real_name": "系统管理员"},
    {"username": "salesman1", "password": "sales123", "role": "salesman", "real_name": "业务员张三"},
    {"username": "salesman2", "password": "sales123", "role": "salesman", "real_name": "业务员李四"},
    {"username": "reviewer1", "password": "review123", "role": "reviewer", "real_name": "审核员王五"},
    {"username": "reviewer2", "password": "review123", "role": "reviewer", "real_name": "审核员赵六"},
]


def seed():
    db = SessionLocal()
    try:
        # 1. Create users
        user_ids = {}
        for u in DEFAULT_USERS:
            existing = db.query(User).filter(User.username == u["username"]).first()
            if not existing:
                user = User(
                    username=u["username"],
                    password_hash=hash_password(u["password"]),
                    role=u["role"],
                    real_name=u["real_name"],
                )
                db.add(user)
                db.flush()
                user_ids[u["username"]] = user.id
                print(f"创建用户: {u['username']} ({u['real_name']})")
            else:
                user_ids[u["username"]] = existing.id

        salesman1_id = user_ids["salesman1"]
        salesman2_id = user_ids["salesman2"]
        reviewer1_id = user_ids["reviewer1"]
        reviewer2_id = user_ids["reviewer2"]
        admin_id = user_ids["admin"]

        # 2. Check if we already have customers
        existing_customers = db.query(Customer).count()
        if existing_customers > 0:
            print("已有客户数据，跳过种子数据生成")
            db.commit()
            return

        # 3. Create customers
        customers_data = [
            {
                "name": "陈明辉", "id_number": "110101198501011239", "phone": "13800138001",
                "education": "本科", "current_title": "工程师", "current_title_year": 2019,
                "work_unit": "中建第三工程有限公司", "position": "项目经理",
                "professional_years": 8,
                "assigned_salesman_id": salesman1_id,
                "project_experiences": '[{"name":"XX商业综合体项目","start_date":"2022-03","end_date":"2023-06","role":"技术负责人","description":"负责主体结构施工方案编制与技术交底"},{"name":"XX住宅楼项目","start_date":"2021-01","end_date":"2022-02","role":"施工员","description":"负责现场施工管理与质量控制"}]',
            },
            {
                "name": "王晓芳", "id_number": "310101199002022349", "phone": "13900139002",
                "education": "硕士研究生", "current_title": "讲师", "current_title_year": 2020,
                "work_unit": "XX职业技术学院", "position": "专业教师",
                "professional_years": 5,
                "assigned_salesman_id": salesman1_id,
                "project_experiences": '[{"name":"省级教改项目","start_date":"2023-01","end_date":"2024-01","role":"主持人","description":"主持《高职工程类专业实践教学改革研究》教改项目"}]',
            },
            {
                "name": "刘志强", "id_number": "440101198703033459", "phone": "13700137003",
                "education": "大专", "current_title": "助理工程师", "current_title_year": 2018,
                "work_unit": "广州XX电子科技有限公司", "position": "技术主管",
                "professional_years": 6,
                "assigned_salesman_id": salesman1_id,
                "project_experiences": "",
            },
            {
                "name": "赵雪梅", "id_number": "510101199104044562", "phone": "13600136004",
                "education": "本科", "current_title": "主治医师", "current_title_year": 2021,
                "work_unit": "成都XX区人民医院", "position": "内科医师",
                "professional_years": 7,
                "assigned_salesman_id": salesman2_id,
                "project_experiences": "",
            },
            {
                "name": "孙建国", "id_number": "330101198205055676", "phone": "13500135005",
                "education": "本科", "current_title": "工程师", "current_title_year": 2017,
                "work_unit": "杭州XX建筑设计院", "position": "结构设计师",
                "professional_years": 10,
                "assigned_salesman_id": salesman2_id,
                "project_experiences": '[{"name":"XX高层住宅项目","start_date":"2022-06","end_date":"2023-12","role":"结构专业负责人","description":"负责30层高层住宅结构设计与施工图审查"},{"name":"XX产业园项目","start_date":"2020-03","end_date":"2021-08","role":"设计师","description":"参与钢结构厂房设计"}]',
            },
            {
                "name": "周丽华", "id_number": "420101198806066786", "phone": "13400134006",
                "education": "硕士研究生", "current_title": "工程师", "current_title_year": 2022,
                "work_unit": "武汉XX环保工程有限公司", "position": "环保工程师",
                "professional_years": 4,
                "assigned_salesman_id": salesman1_id,
                "project_experiences": "",
            },
            {
                "name": "吴伟强", "id_number": "500101199307077899", "phone": "13300133007",
                "education": "本科", "current_title": "助理工程师", "current_title_year": 2020,
                "work_unit": "重庆XX路桥工程有限公司", "position": "桥梁设计师",
                "professional_years": 3,
                "assigned_salesman_id": salesman2_id,
                "project_experiences": "",
            },
            {
                "name": "郑雅文", "id_number": "610101198508088907", "phone": "13200132008",
                "education": "博士研究生", "current_title": "副研究员", "current_title_year": 2018,
                "work_unit": "西安XX研究院", "position": "课题组长",
                "professional_years": 8,
                "assigned_salesman_id": salesman1_id,
                "project_experiences": '[{"name":"国家自然科学基金项目","start_date":"2023-01","end_date":"2025-12","role":"项目负责人","description":"主持面上项目《新型纳米材料在环境治理中的应用研究》"}]',
            },
        ]

        created_customers = []
        for c in customers_data:
            c["name_pinyin"] = get_pinyin_initial(c["name"])
            customer = Customer(**c)
            db.add(customer)
            db.flush()
            created_customers.append(customer)
            print(f"创建客户: {c['name']}")

        # 4. Create applications
        applications_data = [
            # 陈明辉 - 初次申报（进行中）
            {"customer_idx": 0, "professional_category": "建筑工程", "title_level": "高级工程师", "status": "资料补充"},
            # 王晓芳 - 已完成资料等待提交机构
            {"customer_idx": 1, "professional_category": "教育教学", "title_level": "副教授", "status": "完成资料"},
            # 刘志强 - 提交评审机构审核中
            {"customer_idx": 2, "professional_category": "电子信息", "title_level": "高级工程师", "status": "提交评审机构审核"},
            # 赵雪梅 - 返修
            {"customer_idx": 3, "professional_category": "医疗卫生", "title_level": "副主任医师", "status": "返修"},
            # 孙建国 - 已通过
            {"customer_idx": 4, "professional_category": "建筑设计", "title_level": "高级工程师", "status": "通过"},
            # 孙建国 - 二次申报（另一专业）
            {"customer_idx": 4, "professional_category": "土木工程", "title_level": "正高级工程师", "status": "初次申报"},
            # 周丽华 - 初次申报
            {"customer_idx": 5, "professional_category": "环境工程", "title_level": "高级工程师", "status": "初次申报"},
            # 吴伟强 - 不通过
            {"customer_idx": 6, "professional_category": "道路桥梁", "title_level": "高级工程师", "status": "不通过"},
            # 郑雅文 - 资料补充
            {"customer_idx": 7, "professional_category": "材料科学", "title_level": "研究员", "status": "资料补充"},
        ]

        created_apps = []
        for app_data in applications_data:
            customer = created_customers[app_data["customer_idx"]]
            app = Application(
                customer_id=customer.id,
                professional_category=app_data["professional_category"],
                title_level=app_data["title_level"],
                status=app_data["status"],
                batch_number=f"BATCH-{uuid.uuid4().hex[:8].upper()}",
            )
            db.add(app)
            db.flush()
            created_apps.append(app)
            print(f"创建申报批次: {customer.name} - {app_data['professional_category']} - {app_data['status']}")

        # Set some submitted_at dates
        if len(created_apps) > 2:
            created_apps[2].submitted_at = datetime.utcnow() - timedelta(days=5)
            created_apps[2].institution_name = "广东省人力资源和社会保障厅"
        if len(created_apps) > 3:
            created_apps[3].submitted_at = datetime.utcnow() - timedelta(days=10)
            created_apps[3].institution_name = "成都市人力资源和社会保障局"
        if len(created_apps) > 4:
            created_apps[4].submitted_at = datetime.utcnow() - timedelta(days=30)
            created_apps[4].institution_name = "杭州市人力资源和社会保障局"
        if len(created_apps) > 7:
            created_apps[7].submitted_at = datetime.utcnow() - timedelta(days=20)
            created_apps[7].institution_name = "重庆市人力资源和社会保障局"

        # 5. Create materials
        material_categories = ["身份证明", "学历学位", "职称证书", "聘用/劳动合同", "业绩成果", "论文著作", "继续教育"]

        # For specific applications, create sample materials
        apps_with_materials = [
            (0, ["身份证明", "学历学位", "职称证书", "聘用/劳动合同"]),
            (1, ["身份证明", "学历学位", "职称证书", "聘用/劳动合同", "业绩成果", "继续教育"]),
            (2, ["身份证明", "学历学位", "职称证书", "聘用/劳动合同", "业绩成果", "继续教育"]),
            (3, ["身份证明", "学历学位", "职称证书", "聘用/劳动合同"]),
            (4, ["身份证明", "学历学位", "职称证书", "聘用/劳动合同", "业绩成果", "论文著作", "继续教育"]),
            (5, ["身份证明", "学历学位"]),
            (8, ["身份证明", "学历学位", "职称证书"]),
        ]

        sample_filenames = {
            "身份证明": ["身份证正反面扫描件.pdf"],
            "学历学位": ["学士学位证书.pdf", "毕业证书.pdf"],
            "职称证书": ["工程师资格证书.pdf"],
            "聘用/劳动合同": ["劳动合同扫描件.pdf"],
            "业绩成果": ["项目验收报告.pdf", "获奖证书.pdf"],
            "论文著作": ["核心期刊发表论文.pdf", "SCI论文.pdf"],
            "继续教育": ["继续教育学时证明.pdf"],
        }

        for app_idx, categories in apps_with_materials:
            if app_idx >= len(created_apps):
                continue
            app = created_apps[app_idx]
            customer = created_customers[applications_data[app_idx]["customer_idx"]]
            # 通过归属业务员定位客户 NAS 目录，保证与下载路径一致
            salesman = None
            if customer.assigned_salesman_id:
                salesman = db.query(User).filter(User.id == customer.assigned_salesman_id).first()
            customer_rel = customer_dir(
                year=customer.created_at.year,
                salesman_name=salesman.username if salesman else "",
                customer_name=customer.name,
                initial=customer.name_pinyin or "",
            )

            for cat in categories:
                filenames = sample_filenames.get(cat, ["材料.pdf"])
                for fn in filenames:
                    content = f"这是示例文件: {fn}\n用于职称申报系统测试。\n".encode("utf-8")
                    rel_path = save_file(customer_rel, cat, fn, content)

                    material = Material(
                        application_id=app.id,
                        category=cat,
                        filename=fn,
                        file_path=rel_path,
                        file_size=len(content),
                        uploader_id=salesman1_id,
                        audit_status="待审核",
                    )
                    db.add(material)
            db.flush()
            print(f"  -> 为申报批次 #{app.id} 添加了材料")

        # 6. Create reviews
        # For application 1 (王晓芳 - 完成资料), create some review records
        if len(created_apps) > 1:
            app1_materials = db.query(Material).filter(Material.application_id == created_apps[1].id).all()
            for mat in app1_materials[:3]:
                review = Review(
                    material_id=mat.id,
                    application_id=created_apps[1].id,
                    reviewer_id=reviewer1_id,
                    result="通过",
                    description="材料齐全，符合要求",
                )
                db.add(review)
                mat.audit_status = "已通过"

            # Add one flagged material
            if len(app1_materials) > 3:
                flagged_mat = app1_materials[3]
                review = Review(
                    material_id=flagged_mat.id,
                    application_id=created_apps[1].id,
                    reviewer_id=reviewer1_id,
                    result="退回",
                    issue_type="材料缺失",
                    description="缺少近三年的继续教育学时证明，请补充完整",
                )
                db.add(review)
                flagged_mat.audit_status = "已标记问题"

        # For application 3 (赵雪梅 - 返修), create review records with issues
        if len(created_apps) > 3:
            app3_materials = db.query(Material).filter(Material.application_id == created_apps[3].id).all()
            for mat in app3_materials[:2]:
                review = Review(
                    material_id=mat.id,
                    application_id=created_apps[3].id,
                    reviewer_id=reviewer2_id,
                    result="退回",
                    issue_type="内容错误" if mat.category == "职称证书" else "材料缺失",
                    description="主治医师资格证书扫描件不清晰，请重新上传高清版本" if mat.category == "职称证书" else "缺少聘用合同，请补充",
                )
                db.add(review)
                mat.audit_status = "已标记问题"

        print("创建审核记录")

        # 7. Create feedbacks
        # For application 3 (返修)
        if len(created_apps) > 3:
            fb = Feedback(
                application_id=created_apps[3].id,
                feedback_type="返修",
                content="机构审核意见：主治医师资格证书扫描件模糊，无法辨识证书编号。缺少聘用合同原件扫描件。",
                created_by_id=salesman2_id,
            )
            db.add(fb)
            print("创建机构反馈记录")

        # For application 4 (通过)
        if len(created_apps) > 4:
            fb = Feedback(
                application_id=created_apps[4].id,
                feedback_type="通过",
                content="恭喜，高级工程师职称评审已通过。",
                created_by_id=salesman2_id,
            )
            db.add(fb)

        # For application 7 (不通过)
        if len(created_apps) > 7:
            fb = Feedback(
                application_id=created_apps[7].id,
                feedback_type="不通过",
                content="经评审，申报材料不符合高级工程师评审条件，工作年限不足。",
                created_by_id=salesman2_id,
            )
            db.add(fb)


        # 8. Create operation logs
        log_entries = [
            (created_apps[0], created_customers[0], "客户自助提交", "客户通过自助链接提交基本信息", salesman1_id, "客户"),
            (created_apps[1], created_customers[1], "客户自助提交", "客户通过自助链接提交基本信息", salesman1_id, "客户"),
            (created_apps[0], created_customers[0], "上传材料", "上传: 身份证正反面扫描件.pdf", salesman1_id, "材料"),
            (created_apps[0], created_customers[0], "上传材料", "上传: 学士学位证书.pdf", salesman1_id, "材料"),
            (created_apps[1], created_customers[1], "上传材料", "上传: 身份证正反面扫描件.pdf", salesman1_id, "材料"),
            (created_apps[2], created_customers[2], "提交评审机构", "提交至: 广东省人力资源和社会保障厅", salesman1_id, "申报"),
            (created_apps[4], created_customers[4], "提交评审机构", "提交至: 杭州市人力资源和社会保障局", salesman2_id, "申报"),
        ]

        from models import User as UserModel
        for app, customer, action, detail, actor_id, resource_type in log_entries:
            actor = db.query(UserModel).filter(UserModel.id == actor_id).first()
            log = OperationLog(
                user_id=actor_id,
                username=actor.username if actor else "unknown",
                action=action,
                resource_type=resource_type,
                resource_id=app.id,
                new_value={"detail": detail},
            )
            db.add(log)

        print("创建操作日志")

        db.commit()

        print("\n初始化完成。默认账号:")
        print("  管理员: admin / admin123")
        print("  业务员: salesman1 / sales123, salesman2 / sales123")
        print("  审核员: reviewer1 / review123, reviewer2 / review123")
        print(f"\n测试数据: {len(created_customers)} 位客户, {len(created_apps)} 个申报批次")

    finally:
        db.close()


if __name__ == "__main__":
    seed()
