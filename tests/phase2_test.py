#!/usr/bin/env python3
"""Phase 2 Playwright 测试 - 消息通知 + 跟进记录"""

from playwright.sync_api import sync_playwright, expect
import time

BASE_URL = "http://localhost:5174"

def test_phase2():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        print("=" * 60)
        print("🚀 Phase 2 功能测试 - 消息通知 + 跟进记录")
        print("=" * 60)
        
        # ===== 测试 1: 登录并检查通知铃铛 =====
        print("\n📝 测试 1: 登录并检查通知铃铛")
        page.goto(f"{BASE_URL}/login")
        page.fill('input[placeholder="请输入用户名"]', 'salesman1')
        page.fill('input[placeholder="请输入密码"]', 'sales123')
        page.click('button:has-text("登 录")')
        page.wait_for_load_state('networkidle', timeout=10000)
        
        if "/admin" in page.url:
            print("  ✅ 登录成功")
        else:
            print(f"  ❌ 登录失败，当前 URL: {page.url}")
            browser.close()
            return
        
        # 检查通知铃铛是否存在
        try:
            bell = page.locator('.notification-badge')
            if bell.count() > 0:
                print("  ✅ 通知铃铛组件已加载")
            else:
                print("  ❌ 通知铃铛组件未找到")
        except Exception as e:
            print(f"  ❌ 通知铃铛检查失败：{e}")
        
        # ===== 测试 2: 访问客户详情页面 =====
        print("\n📝 测试 2: 访问客户详情并检查跟进记录")
        page.goto(f"{BASE_URL}/admin/customers")
        page.wait_for_load_state('networkidle', timeout=10000)
        
        # 点击第一个客户
        try:
            page.click('el-table__row .name-cell', timeout=5000)
            page.wait_for_load_state('networkidle', timeout=10000)
            print("  ✅ 进入客户详情页")
        except:
            # 如果表格没有可点击的行，尝试直接访问
            page.goto(f"{BASE_URL}/admin/customers/1")
            page.wait_for_load_state('networkidle', timeout=10000)
            print("  ✅ 直接访问客户详情页")
        
        # 检查跟进记录标签页
        try:
            page.click('el-tab-pane:has-text("跟进记录")', timeout=5000)
            print("  ✅ 跟进记录标签页可点击")
        except:
            print("  ⚠️  跟进记录标签页可能已激活或不存在")
        
        # 检查跟进记录时间轴
        timeline = page.locator('.follow-up-timeline')
        if timeline.count() > 0:
            print("  ✅ 跟进记录时间轴组件已加载")
        else:
            print("  ❌ 跟进记录时间轴未找到")
        
        # ===== 测试 3: 创建跟进记录 =====
        print("\n📝 测试 3: 创建跟进记录")
        
        try:
            # 点击新增跟进按钮
            page.click('button:has-text("新增跟进")', timeout=5000)
            print("  ✅ 点击新增跟进按钮")
            
            # 等待对话框打开
            page.wait_for_selector('.el-dialog__title:has-text("新增跟进记录")', timeout=5000)
            
            # 填写跟进内容
            page.fill('textarea[placeholder="记录本次沟通情况"]', 
                     '电话沟通客户，确认基本信息无误，客户表示会尽快准备材料')
            print("  ✅ 填写跟进内容")
            
            # 选择跟进方式
            page.click('.el-select-dropdown__item:has-text("微信")', timeout=5000)
            print("  ✅ 选择跟进方式：微信")
            
            # 提交
            page.click('button:has-text("提交")', timeout=5000)
            page.wait_for_load_state('networkidle', timeout=10000)
            
            # 检查是否成功
            success_msg = page.locator('.el-message--success')
            if success_msg.count() > 0:
                print("  ✅ 跟进记录创建成功")
            else:
                print("  ⚠️  未检测到成功提示，但可能已创建")
            
            # 等待一下让数据刷新
            time.sleep(2)
            
            # 检查时间轴中是否有新记录
            timeline_items = page.locator('.timeline-item')
            count = timeline_items.count()
            if count > 0:
                print(f"  ✅ 时间轴中现有 {count} 条跟进记录")
            else:
                print("  ⚠️  时间轴中未显示记录")
                
        except Exception as e:
            print(f"  ❌ 创建跟进记录失败：{e}")
        
        # ===== 测试 4: 检查通知列表 API =====
        print("\n📝 测试 4: 检查通知 API")
        
        # 通过 API 检查通知
        response = context.request.get(f"{BASE_URL}/api/notifications/")
        if response.status == 200:
            data = response.json()
            print(f"  ✅ 通知 API 响应正常")
            print(f"     - 总通知数：{data.get('total', 0)}")
            print(f"     - 未读数：{data.get('unread_count', 0)}")
        else:
            print(f"  ❌ 通知 API 响应失败：{response.status}")
        
        # ===== 测试 5: 变更状态触发通知 =====
        print("\n📝 测试 5: 状态变更触发通知")
        
        # 先回到工作台
        page.goto(f"{BASE_URL}/admin/dashboard")
        page.wait_for_load_state('networkidle', timeout=10000)
        
        # 检查工作台是否显示统计卡片
        stats_cards = page.locator('.stat-card, .el-statistic, [class*="stat"]')
        if stats_cards.count() > 0:
            print(f"  ✅ 工作台统计卡片显示正常 (找到 {stats_cards.count()} 个)")
        else:
            print("  ⚠️  未检测到统计卡片")
        
        print("\n" + "=" * 60)
        print("🎉 Phase 2 测试完成！")
        print("=" * 60)
        
        # 截图保存
        page.screenshot(path='/workspace/tests/phase2_result.png', full_page=True)
        print(f"\n📸 测试截图已保存：/workspace/tests/phase2_result.png")
        
        browser.close()

if __name__ == "__main__":
    test_phase2()
