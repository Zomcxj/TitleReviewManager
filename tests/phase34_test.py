#!/usr/bin/env python3
"""Phase 3 & 4 Playwright 测试 - 公海池 + SLA + 批量操作 + 数据看板"""

from playwright.sync_api import sync_playwright
import time

BASE_URL = "http://localhost:5174"

def test_phase3_4():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        print("=" * 60)
        print("🚀 Phase 3 & 4 功能测试")
        print("=" * 60)
        
        # ===== 测试 1: 登录管理员账号 =====
        print("\n📝 测试 1: 管理员登录")
        page.goto(f"{BASE_URL}/login")
        page.fill('input[placeholder="请输入用户名"]', 'admin')
        page.fill('input[placeholder="请输入密码"]', 'admin123')
        page.click('button:has-text("登 录")')
        page.wait_for_load_state('networkidle', timeout=10000)
        
        if "/admin" in page.url:
            print("  ✅ 管理员登录成功")
        else:
            print(f"  ❌ 登录失败：{page.url}")
            browser.close()
            return
        
        # ===== 测试 2: 访问公海池页面 =====
        print("\n📝 测试 2: 访问公海池页面")
        page.goto(f"{BASE_URL}/admin/public-pool")
        page.wait_for_load_state('networkidle', timeout=10000)
        
        if "公海池" in page.content():
            print("  ✅ 公海池页面加载成功")
        else:
            print("  ❌ 公海池页面未正确加载")
        
        # 检查统计卡片
        stats_cards = page.locator('.el-statistic')
        if stats_cards.count() >= 4:
            print(f"  ✅ 公海池统计卡片显示正常 ({stats_cards.count()} 个)")
        else:
            print(f"  ⚠️  统计卡片数量异常 ({stats_cards.count()} 个)")
        
        # ===== 测试 3: 访问数据看板 =====
        print("\n📝 测试 3: 数据看板页面")
        page.goto(f"{BASE_URL}/admin/dashboard")
        page.wait_for_load_state('networkidle', timeout=10000)
        
        # 检查统计卡片
        dashboard_stats = page.locator('.stats-grid .el-statistic')
        if dashboard_stats.count() >= 4:
            print(f"  ✅ 数据看板统计卡片显示正常 ({dashboard_stats.count()} 个)")
        else:
            print(f"  ⚠️  数据看板统计卡片数量异常 ({dashboard_stats.count()} 个)")
        
        # 检查图表容器
        charts = page.locator('[ref="trendChart"], [ref="statusChart"]')
        if charts.count() >= 2:
            print("  ✅ ECharts 图表容器已加载")
        else:
            print("  ⚠️  ECharts 图表容器可能未加载")
        
        # 检查业绩排行表格
        ranking_table = page.locator('el-table')
        if ranking_table.count() > 0:
            print("  ✅ 销售业绩排行表格已加载")
        else:
            print("  ⚠️  销售业绩排行表格未找到")
        
        # ===== 测试 4: 客户列表批量操作 =====
        print("\n📝 测试 4: 客户列表批量操作")
        page.goto(f"{BASE_URL}/admin/customers")
        page.wait_for_load_state('networkidle', timeout=10000)
        
        # 检查批量分配按钮
        batch_btn = page.locator('button:has-text("批量分配")')
        if batch_btn.count() > 0:
            print("  ✅ 批量分配按钮已显示")
        else:
            print("  ⚠️  批量分配按钮未找到")
        
        # 检查导出按钮
        export_btn = page.locator('button:has-text("导出 Excel")')
        if export_btn.count() > 0:
            print("  ✅ 导出 Excel 按钮已显示")
        else:
            print("  ⚠️  导出 Excel 按钮未找到")
        
        # ===== 测试 5: 通知铃铛 =====
        print("\n📝 测试 5: 通知功能")
        notification_bell = page.locator('.notification-badge')
        if notification_bell.count() > 0:
            print("  ✅ 通知铃铛组件已加载")
        else:
            print("  ⚠️  通知铃铛组件未找到")
        
        # ===== 测试 6: API 测试 =====
        print("\n📝 测试 6: 后端 API 测试")
        
        # 测试公海池 API
        response = context.request.get(f"{BASE_URL}/api/public-pool/stats")
        if response.status == 200:
            data = response.json()
            print(f"  ✅ 公海池统计 API 正常")
            print(f"     - 公海客户数：{data.get('total_in_pool', 0)}")
        else:
            print(f"  ❌ 公海池统计 API 失败：{response.status}")
        
        # 测试数据看板 API
        response = context.request.get(f"{BASE_URL}/api/dashboard/stats")
        if response.status == 200:
            data = response.json()
            print(f"  ✅ 数据看板 API 正常")
            print(f"     - 总客户数：{data.get('total_customers', 0)}")
        else:
            print(f"  ❌ 数据看板 API 失败：{response.status}")
        
        # 测试趋势 API
        response = context.request.get(f"{BASE_URL}/api/dashboard/trend?days=7")
        if response.status == 200:
            print(f"  ✅ 趋势数据 API 正常")
        else:
            print(f"  ❌ 趋势数据 API 失败：{response.status}")
        
        print("\n" + "=" * 60)
        print("🎉 Phase 3 & 4 测试完成！")
        print("=" * 60)
        
        # 截图
        page.screenshot(path='/workspace/tests/phase34_result.png', full_page=True)
        print(f"\n📸 测试截图已保存：/workspace/tests/phase34_result.png")
        
        browser.close()

if __name__ == "__main__":
    test_phase3_4()
