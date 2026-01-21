import os
import time
import sys
import random
from playwright.sync_api import sync_playwright

# --- 全局配置 ---
HIDENCLOUD_COOKIE = os.environ.get('HIDENCLOUD_COOKIE')
HIDENCLOUD_EMAIL = os.environ.get('HIDENCLOUD_EMAIL')
HIDENCLOUD_PASSWORD = os.environ.get('HIDENCLOUD_PASSWORD')

BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"
SERVICE_URL = f"{BASE_URL}/service/135325/manage" # 请确认这是你的服务ID
COOKIE_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
"""

def handle_cloudflare(page):
    """
    通用验证处理逻辑
    """
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    if page.locator(iframe_selector).count() == 0:
        return True

    log("⚠️ 检测到 Cloudflare 验证...")
    start_time = time.time()
    
    while time.time() - start_time < 60:
        if page.locator(iframe_selector).count() == 0:
            log("✅ 验证通过！")
            return True

        try:
            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            if checkbox.is_visible():
                log("点击验证复选框...")
                time.sleep(random.uniform(0.5, 1.5))
                checkbox.click()
                log("已点击，等待验证结果...")
                time.sleep(5)
            else:
                time.sleep(1)
        except Exception:
            pass
            
    log("❌ 验证超时。")
    return False

def login(page):
    log("开始登录流程...")
    
    # 1. Cookie 登录尝试
    if HIDENCLOUD_COOKIE:
        log("尝试 Cookie 登录...")
        try:
            page.context.add_cookies([{
                'name': COOKIE_NAME, 'value': HIDENCLOUD_COOKIE,
                'domain': 'dash.hidencloud.com', 'path': '/',
                'expires': int(time.time()) + 3600 * 24 * 365,
                'httpOnly': True, 'secure': True, 'sameSite': 'Lax'
            }])
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            handle_cloudflare(page)
            
            if "auth/login" not in page.url:
                log("✅ Cookie 登录成功！")
                return True
            log("Cookie 失效。")
        except:
            pass

def renew_service(page):
    try:
        log("进入续费流程...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        handle_cloudflare(page)

        # --- 修改点开始：智能重试点击 Renew ---
        log("准备点击 'Renew' 按钮...")
        renew_btn = page.locator('button:has-text("Renew")')
        create_btn = page.locator('button:has-text("Create Invoice")')
        
        # 尝试最多 3 次点击，直到弹窗出现
        modal_opened = False
        for i in range(3):
            try:
                renew_btn.wait_for(state="visible", timeout=10000)
                # 滚动到可见区域，防止被底部栏遮挡
                renew_btn.scroll_into_view_if_needed()
                
                log(f"第 {i+1} 次尝试点击 'Renew'...")
                renew_btn.click()
                
                # 点击后等待 3 秒，检查 Create Invoice 是否出来
                log("等待弹窗出现...")
                try:
                    create_btn.wait_for(state="visible", timeout=5000)
                    modal_opened = True
                    log("✅ 弹窗已成功弹出！")
                    break # 成功了，跳出循环
                except:
                    log("⚠️ 弹窗未出现，可能是点击未响应，准备重试...")
                    time.sleep(2)
            except Exception as e:
                log(f"点击尝试出错: {e}")
        
        if not modal_opened:
            log("❌ 错误：尝试多次后，续费弹窗仍未出现。")
            page.screenshot(path="renew_modal_failed.png")
            return False
        # --- 修改点结束 ---

        # 再次检查盾 (防止点击 Renew 后弹出验证)
        handle_cloudflare(page)
        
        log("点击 'Create Invoice'...")
        create_btn.click()
        
        log("等待发票生成...")
        new_invoice_url = None
        start_wait = time.time()
        
        # 监控发票跳转 (90秒)
        while time.time() - start_wait < 90:
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面已跳转: {new_invoice_url}")
                break
            
            if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
                log("⚠️ 遇到拦截，尝试处理...")
                handle_cloudflare(page)
            
            time.sleep(1)
        
        if not new_invoice_url:
            log("❌ 未能进入发票页面，超时。")
            page.screenshot(path="renew_stuck_invoice.png")
            return False

        if page.url != new_invoice_url:
            page.goto(new_invoice_url)
            
        handle_cloudflare(page)

        log("查找 'Pay' 按钮...")
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click()
        
        log("✅ 'Pay' 按钮已点击。")
        time.sleep(5)
        return True

    except Exception as e:
        log(f"❌ 续费异常: {e}")
        page.screenshot(path="renew_error.png")
        return False

def main():
    if not HIDENCLOUD_COOKIE and not (HIDENCLOUD_EMAIL and HIDENCLOUD_PASSWORD):
        sys.exit(1)

    with sync_playwright() as p:
        try:
            log("启动官方 Chrome (Linux版)...")
            browser = p.chromium.launch(
                channel="chrome",
                headless=False,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled', '--disable-infobars']
            )
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36'
            )
            page = context.new_page()
            page.add_init_script(STEALTH_JS)

            if not login(page):
                sys.exit(1)

            if not renew_service(page):
                sys.exit(1)

            log("🎉 任务全部完成！")
        except Exception as e:
            log(f"💥 严重错误: {e}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
