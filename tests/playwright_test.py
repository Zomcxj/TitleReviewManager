#!/usr/bin/env python3
"""
职称服务管理平台 - Playwright 自动化测试
测试核心功能流程
"""

from playwright.sync_api import sync_playwright, expect
import json
import time

BASE_URL = "http://localhost:5173"
API_URL = "http://localhost:8000"

# 测试账号
TEST_USERS = [
    {"username": "admin", "password": "admin123", "role": "管理员"},
    {"username": "salesman1", "password": "sales123", "role": "业务员"},
    {"username": "reviewer1", "password": "review123", "role": "审核员"},
]


def test_login(page, user):
    """测试登录功能"""
    print(f"\n📝 测试登录 - {user['role']} ({user['username']})")
    
    # 访问登录页
    page.goto(f"{BASE_URL}/login")
    expect(page).to_have_title("职称服务内部管理平台")
    
    # 填写表单
    page.fill('input[placeholder="请输入用户名"]', user["username"])
    page.fill('input[placeholder="请输入密码"]', user["password"])
    
    # 点击登录
    page.click('button:has-text("登 录")')
    
    # 等待跳转 - 使用 wait_for_load_state 而不是 wait_for_url
    page.wait_for_load_state('networkidle', timeout=5000)
    
    # 验证当前 URL
    current_url = page.url
    assert '/admin' in current_url, f"登录后应该跳转到 /admin，实际：{current_url}"
    
    # 验证欢迎语
    welcome = page.locator(".welcome-text h2")
    expect(welcome).to_be_visible()
    
    print(f"  ✅ 登录成功，当前用户：{user['username']}，URL：{current_url}")
    return True


def test_dashboard(page):
    """测试工作台"""
    print("\n📊 测试工作台")
    
    # 验证统计卡片
    stat_cards = page.locator(".stat-card")
    count = stat_cards.count()
    assert count > 0, "统计卡片应该显示"
    print(f"  ✅ 显示 {count} 个统计卡片")
    
    # 验证表格区域存在
    table_area = page.locator(".el-table")
    expect(table_area).to_be_visible()
    print(f"  ✅ 最近客户表格显示正常")
    
    # 验证时间问候语
    welcome_text = page.locator(".welcome-text h2").inner_text()
    assert any(greeting in welcome_text for greeting in ["早上好", "下午好", "晚上好"])
    print(f"  ✅ 时间问候语：{welcome_text}")
    
    return True


def test_customer_list(page):
    """测试客户列表"""
    print("\n👥 测试客户列表")
    
    # 导航到客户管理
    page.click('el-menu-item[index="/admin/customers"]')
    page.wait_for_timeout(1000)
    
    # 验证表格
    customer_table = page.locator(".el-table")
    expect(customer_table).to_be_visible()
    
    # 验证客户数量
    rows = page.locator(".el-table__row")
    count = rows.count()
    print(f"  ✅ 显示 {count} 位客户")
    
    # 验证搜索框
    search_input = page.locator('input[placeholder="搜索姓名 / 身份证 / 手机号"]')
    expect(search_input).to_be_visible()
    print(f"  ✅ 搜索功能可用")
    
    # 验证状态筛选
    status_select = page.locator('el-select[placeholder="状态筛选"]')
    expect(status_select).to_be_visible()
    print(f"  ✅ 状态筛选功能可用")
    
    # 测试查看详情
    detail_btn = page.locator('.el-button:has-text("详情")').first
    if detail_btn.count() > 0:
        detail_btn.click()
        page.wait_for_url("**/customers/**", timeout=5000)
        print(f"  ✅ 查看详情页面跳转成功")
    
    return True


def test_customer_detail(page):
    """测试客户详情"""
    print("\n📋 测试客户详情")
    
    # 验证基本信息标签页
    basic_tab = page.locator('el-tab-pane[name="basic"]')
    expect(basic_tab).to_be_visible()
    print(f"  ✅ 基本信息标签页显示")
    
    # 验证材料管理标签页
    materials_tab = page.locator('el-tab-pane[name="materials"]')
    expect(materials_tab).to_be_visible()
    print(f"  ✅ 材料管理标签页显示")
    
    # 验证申报批次侧边栏
    sidebar = page.locator(".sidebar-card")
    expect(sidebar).to_be_visible()
    print(f"  ✅ 申报批次侧边栏显示")
    
    return True


def test_registration_links(page):
    """测试注册链接管理（仅管理员/业务员）"""
    print("\n🔗 测试注册链接管理")
    
    # 导航到注册链接
    page.click('el-menu-item[index="/admin/registration-links"]')
    page.wait_for_timeout(1000)
    
    # 验证页面
    create_btn = page.locator('button:has-text("创建链接")')
    expect(create_btn).to_be_visible()
    print(f"  ✅ 创建链接按钮显示")
    
    return True


def test_review_workspace(page):
    """测试审核工作台（仅管理员/审核员）"""
    print("\n✅ 测试审核工作台")
    
    # 导航到审核工作台
    page.click('el-menu-item[index="/admin/reviews"]')
    page.wait_for_timeout(1000)
    
    # 验证待审核列表
    pending_list = page.locator(".panel-title:has-text('待审核列表')")
    expect(pending_list).to_be_visible()
    print(f"  ✅ 待审核列表显示")
    
    return True


def run_tests():
    """运行所有测试"""
    print("=" * 60)
    print("🚀 职称服务管理平台 - Playwright 自动化测试")
    print("=" * 60)
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for user in TEST_USERS:
            print(f"\n{'='*60}")
            print(f"👤 测试用户：{user['role']} - {user['username']}")
            print(f"{'='*60}")
            
            context = browser.new_context()
            page = context.new_page()
            
            try:
                # 1. 测试登录
                test_login(page, user)
                
                # 2. 测试工作台
                test_dashboard(page)
                
                # 3. 测试客户列表
                test_customer_list(page)
                
                # 4. 测试客户详情
                test_customer_detail(page)
                
                # 5. 根据角色测试特定功能
                if user["role"] in ["管理员", "业务员"]:
                    test_registration_links(page)
                
                if user["role"] in ["管理员", "审核员"]:
                    test_review_workspace(page)
                
                print(f"\n✅ {user['role']} 所有测试通过！")
                
            except Exception as e:
                print(f"\n❌ {user['role']} 测试失败：{str(e)}")
                # 截图保存错误现场
                page.screenshot(path=f"error_{user['username']}.png")
                
            finally:
                context.close()
        
        browser.close()
    
    print("\n" + "=" * 60)
    print("🎉 所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    run_tests()
