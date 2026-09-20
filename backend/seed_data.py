import random
from datetime import datetime, timedelta, timezone

from database import SessionLocal
from models import Application, Customer, OperationLog, User

db = SessionLocal()

names = ["张三", "李四", "王五", "赵六", "钱七", "孙八", "周九", "吴十", "郑十一", "王十二"]
educations = ["博士", "硕士", "本科", "大专"]
units = ["科技有限公司", "教育集团", "医院", "设计院", "研究所", "制造厂"]
statuses = ["初次申报", "资料补充", "完成资料", "提交评审机构审核", "返修", "通过", "不通过", "二次申报"]
categories = ["工程技术", "教育", "卫生", "科研"]
levels = ["初级", "中级", "高级"]

customers = []
for i in range(100):
    name = random.choice(names) + str(i)
    c = Customer(
        name=name,
        phone=f"138{random.randint(0,99999999):08d}",
        id_number=f"33010019900101{i:04d}",
        education=random.choice(educations),
        work_unit=random.choice(units),
        current_title="工程师",
        current_title_year=random.randint(2015, 2024),
        position="技术总监" if i % 5 == 0 else "工程师",
        professional_years=random.randint(3, 20),
        project_experiences=f"主持{i}项重点项目",
        assigned_salesman_id=random.choice([1,2,3]),
        is_public=(i % 10 == 0),
    )
    if c.is_public:
        c.public_at = datetime.now(timezone.utc) - timedelta(days=random.randint(1,30))
    customers.append(c)

db.add_all(customers)
db.commit()

for c in customers:
    app = Application(
        customer_id=c.id,
        professional_category=random.choice(categories),
        title_level=random.choice(levels),
        status=random.choice(statuses),
        batch_number=f"2024{random.randint(1000,9999)}",
        submitted_at=datetime.now(timezone.utc) - timedelta(days=random.randint(1,60)),
        institution_name="省职称评审中心",
        assigned_reviewer_id=random.choice([4,5,None]),
    )
    db.add(app)

db.commit()
print(f"已生成{len(customers)}条客户和申请数据")

logs = []
for _ in range(50):
    log = OperationLog(
        user_id=random.choice([1,2,3]),
        username=f"user{random.randint(1,3)}",
        action=random.choice(["创建", "更新", "查询", "导出", "审核"]),
        resource_type=random.choice(["customer", "application", "review"]),
        resource_id=random.randint(1,100),
        ip_address=f"192.168.1.{random.randint(1,254)}",
    )
    logs.append(log)

db.add_all(logs)
db.commit()
print(f"已生成{len(logs)}条操作日志")

db.close()
print("数据生成完成")
