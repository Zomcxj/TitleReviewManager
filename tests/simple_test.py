#!/usr/bin/env python3
"""简化版 Playwright 测试 - 调试用"""

from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:5173"

def test():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        # 1. 访问登录页
        print("1. 访问登录页...")
        response = page.goto(f"{BASE_URL}/login")
        print(f"   状态码：{response.status}")
        print(f"   当前 URL: {page.url}")
        
        # 2. 填写登录表单
        print("2. 填写登录表单...")
        page.fill('input[placeholder="请输入用户名"]', 'admin')
        page.fill('input[placeholder="请输入密码"]', 'admin123')
        print("   填写完成")
        
        # 3. 点击登录
        print("3. 点击登录...")
        page.click('button:has-text("登 录")')
        
        # 4. 等待
        print("4. 等待网络空闲...")
        page.wait_for_load_state('networkidle', timeout=10000)
        print(f"   当前 URL: {page.url}")
        
        # 5. 截图
        print("5. 截图...")
        page.screenshot(path='/workspace/tests/login_result.png', full_page=True)
        print("   截图保存：/workspace/tests/login_result.png")
        
        browser.close()

if __name__ == "__main__":
    test()
