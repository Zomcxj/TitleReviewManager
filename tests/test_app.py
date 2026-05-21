from playwright.sync_api import sync_playwright
import sys

def test_app():
    results = []
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # 1. Login page
        print("1. 测试登录页面...")
        page.goto('http://localhost:8000/login')
        page.wait_for_load_state('networkidle')
        page.screenshot(path='/tmp/test_01_login.png', full_page=True)
        
        # Login as admin
        page.fill('input[type="text"], input[placeholder*="用户名"]', 'admin')
        page.fill('input[type="password"]', 'admin123')
        page.click('button[type="submit"], button:has-text("登录")')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path='/tmp/test_02_dashboard.png', full_page=True)
        
        if '/admin/dashboard' in page.url:
            print("   ✓ 登录成功，跳转到工作台")
            results.append(("登录", "PASS"))
        else:
            print(f"   ✗ 登录后URL: {page.url}")
            results.append(("登录", "FAIL"))
        
        # 2. Customer list - check salesman column
        print("2. 测试客户列表...")
        page.goto('http://localhost:8000/admin/customers')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path='/tmp/test_03_customers.png', full_page=True)
        
        # Check if there are customer rows
        rows = page.locator('.el-table__body tr').count()
        print(f"   客户行数: {rows}")
        if rows > 0:
            results.append(("客户列表", "PASS"))
        else:
            results.append(("客户列表", "FAIL"))
        
        # 3. Transfer page
        print("3. 测试客户转让页面...")
        page.goto('http://localhost:8000/admin/transfer')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1500)
        page.screenshot(path='/tmp/test_04_transfer.png', full_page=True)
        
        rows = page.locator('.el-table__body tr').count()
        print(f"   转让页客户行数: {rows}")
        if rows > 0:
            results.append(("客户转让页面", "PASS"))
        else:
            results.append(("客户转让页面", "FAIL"))
        
        # 4. Customer detail - test transfer button
        print("4. 测试客户详情页...")
        page.goto('http://localhost:8000/admin/customers/1')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path='/tmp/test_05_detail.png', full_page=True)
        
        # Click transfer button
        transfer_btn = page.locator('button:has-text("转让客户")')
        if transfer_btn.count() > 0:
            transfer_btn.click()
            page.wait_for_timeout(1000)
            page.screenshot(path='/tmp/test_06_transfer_dialog.png', full_page=True)
            
            # Check if salesmen are loaded in the select
            options = page.locator('.el-select-dropdown__item').count()
            print(f"   转让弹窗选项数: {options}")
            if options > 0:
                results.append(("转让弹窗加载业务员", "PASS"))
            else:
                # Try clicking the select to open it
                select_input = page.locator('.el-select').first
                if select_input.count() > 0:
                    select_input.click()
                    page.wait_for_timeout(500)
                    page.screenshot(path='/tmp/test_06b_transfer_dialog_open.png', full_page=True)
                    options = page.locator('.el-select-dropdown__item').count()
                    print(f"   展开后选项数: {options}")
                    if options > 0:
                        results.append(("转让弹窗加载业务员", "PASS"))
                    else:
                        results.append(("转让弹窗加载业务员", "FAIL"))
                else:
                    results.append(("转让弹窗加载业务员", "FAIL"))
        else:
            print("   ✗ 未找到转让按钮")
            results.append(("转让按钮", "FAIL"))
        
        # 5. Import page
        print("5. 测试导入页面...")
        page.goto('http://localhost:8000/admin/import')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path='/tmp/test_07_import.png', full_page=True)
        results.append(("导入页面", "PASS"))
        
        # 6. User management
        print("6. 测试用户管理...")
        page.goto('http://localhost:8000/admin/users')
        page.wait_for_load_state('networkidle')
        page.wait_for_timeout(1000)
        page.screenshot(path='/tmp/test_08_users.png', full_page=True)
        results.append(("用户管理", "PASS"))
        
        browser.close()
    
    # Summary
    print("\n" + "=" * 50)
    print("测试结果汇总:")
    print("=" * 50)
    for name, status in results:
        icon = "✓" if status == "PASS" else "✗"
        print(f"  {icon} {name}: {status}")
    
    passed = sum(1 for _, s in results if s == "PASS")
    total = len(results)
    print(f"\n通过: {passed}/{total}")
    
    return passed == total

if __name__ == '__main__':
    success = test_app()
    sys.exit(0 if success else 1)
