#!/usr/bin/env python3
"""
职称服务管理平台 - Playwright 自动化测试（v2）
基于实际 Vue 组件结构编写
"""
from playwright.sync_api import sync_playwright, expect
import sys
import os

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

TEST_USERS = [
    {"username": "admin", "password": "admin123", "role": "管理员"},
    {"username": "salesman1", "password": "sales123", "role": "业务员"},
    {"username": "reviewer1", "password": "review123", "role": "审核员"},
]


def test_login(page, user):
    """测试登录"""
    print(f"\n  ▶ 登录 - {user['role']} ({user['username']})")
    page.goto(f"{BASE_URL}/login")
    expect(page).to_have_title("职称服务内部管理平台")

    # 填写用户名
    username_input = page.get_by_placeholder("请输入用户名")
    expect(username_input).to_be_visible()
    username_input.fill(user["username"])

    # 填写密码
    password_input = page.get_by_placeholder("请输入密码")
    expect(password_input).to_be_visible()
    password_input.fill(user["password"])

    # 点击登录按钮（使用 get_by_role 更可靠）
    login_btn = page.get_by_role("button", name="登录")
    expect(login_btn).to_be_visible()
    login_btn.click()

    # 等待页面跳转
    page.wait_for_url("**/admin/**", timeout=10000)
    print(f"  ✅ 登录成功，URL: {page.url}")
    return True


def test_dashboard(page):
    """测试工作台"""
    print("\n  ▶ 工作台验证")

    # 验证统计卡片
    stat_cards = page.locator(".stat-card")
    count = stat_cards.count()
    assert count > 0, "未找到统计卡片"
    print(f"  ✅ 显示 {count} 个统计卡片")

    # 验证申报状态分布区域
    status_dist = page.get_by_text("申报状态分布")
    expect(status_dist).to_be_visible()
    print(f"  ✅ 申报状态分布显示正常")

    return True


def test_customer_list(page):
    """测试客户列表"""
    print("\n  ▶ 客户列表验证")

    # 从侧边栏导航到客户管理
    page.get_by_role("menuitem", name="客户管理").click()
    page.wait_for_url("**/admin/customers", timeout=5000)

    # 验证表格
    table = page.locator(".el-table")
    expect(table).to_be_visible()
    print(f"  ✅ 客户表格显示正常")

    # 验证搜索框
    search_input = page.get_by_placeholder("搜索姓名 / 身份证 / 手机号")
    expect(search_input).to_be_visible()
    print(f"  ✅ 搜索功能可用")

    # 查看第一行详情
    detail_btn = page.get_by_role("button", name="详情").first
    if detail_btn.count() > 0:
        detail_btn.click()
        page.wait_for_url("**/customers/**", timeout=5000)
        print(f"  ✅ 跳转到客户详情页")

    return True


def test_customer_detail(page):
    """测试客户详情"""
    print("\n  ▶ 客户详情验证")

    # 验证基本信息标签页
    basic_tab = page.get_by_role("tab", name="基本信息")
    expect(basic_tab).to_be_visible()
    print(f"  ✅ 基本信息标签页显示")

    # 验证材料管理标签页
    materials_tab = page.get_by_role("tab", name="材料管理")
    expect(materials_tab).to_be_visible()
    print(f"  ✅ 材料管理标签页显示")

    return True


def test_registration_links(page):
    """测试注册链接管理"""
    print("\n  ▶ 注册链接验证")

    # 导航到注册链接
    page.get_by_text("注册链接").click()
    page.wait_for_url("**/registration-links", timeout=5000)

    # 验证生成链接按钮
    create_btn = page.get_by_role("button", name="生成新链接")
    expect(create_btn).to_be_visible()
    print(f"  ✅ 生成新链接按钮显示")

    return True


def test_review_workspace(page):
    """测试审核工作台"""
    print("\n  ▶ 审核工作台验证")

    # 导航到审核工作台（从侧边栏）
    page.get_by_role("menuitem", name="审核工作台").click()
    page.wait_for_url("**/reviews", timeout=5000)

    # 验证页面标题
    page_title = page.get_by_role("heading", name="审核工作台").first
    expect(page_title).to_be_visible()
    print(f"  ✅ 审核工作台页面显示")

    return True


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("  职称服务管理平台 - Playwright 自动化测试 v2")
    print("=" * 60)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        all_pass = True
        for user in TEST_USERS:
            print(f"\n{'='*60}")
            print(f"  👤 测试用户: {user['role']} - {user['username']}")
            print(f"{'='*60}")

            context = browser.new_context(
                viewport={"width": 1440, "height": 900}
            )
            page = context.new_page()

            try:
                # 1. 登录
                test_login(page, user)

                # 2. 工作台
                test_dashboard(page)

                # 3. 客户列表
                test_customer_list(page)

                # 4. 客户详情
                test_customer_detail(page)

                # 5. 角色特定功能
                if user["role"] in ("管理员", "业务员"):
                # 先导航回工作台，确保侧边栏可用
                    page.get_by_role("menuitem", name="工作台", exact=True).click()
                    page.wait_for_url("**/dashboard", timeout=5000)
                    test_registration_links(page)

                if user["role"] in ("管理员", "审核员"):
                    page.get_by_role("menuitem", name="工作台", exact=True).click()
                    page.wait_for_url("**/dashboard", timeout=5000)
                    test_review_workspace(page)

                print(f"\n  ✅ {user['role']} 全部测试通过！")

            except Exception as e:
                all_pass = False
                print(f"\n  ❌ {user['role']} 测试失败: {e}")
                try:
                    page.screenshot(path=f"error_{user['username']}.png", full_page=True)
                    print(f"  📸 已保存截图: error_{user['username']}.png")
                except Exception:
                    pass

            finally:
                context.close()

        browser.close()

    print(f"\n{'='*60}")
    if all_pass:
        print("  🎉 所有测试全部通过！")
    else:
        print(f"  ⚠️  有测试未通过，请检查截图")
    print(f"{'='*60}")

    return 0 if all_pass else 1


if __name__ == "__main__":
    sys.exit(run_tests())
