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
SERVICE_URL = f"{BASE_URL}/service/71879/manage"
COOKIE_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

def log(message):
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

# 基础反指纹 JS (仅移除明显的 webdriver 标记)
STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    // 注意：这里不再伪造 plugins 和 languages，让浏览器使用默认的 Linux 特征，保持一致性
"""

def handle_cloudflare(page):
    """
    通用验证处理逻辑
    """
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    # 快速检测
    if page.locator(iframe_selector).count() == 0:
        return True

    log("⚠️ 检测到 Cloudflare 验证...")
    start_time = time.time()
    
    # 给予 60 秒时间处理
    while time.time() - start_time < 60:
        # 如果 iframe 消失，说明通过
        if page.locator(iframe_selector).count() == 0:
            log("✅ 验证通过！")
            return True

        try:
            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            
            # 如果能看到复选框，就点一下
            if checkbox.is_visible():
                log("点击验证复选框...")
                time.sleep(random.uniform(0.5, 1.5))
                checkbox.click()
                
                # 点击后等待，不要频繁操作
                log("已点击，等待验证结果...")
                time.sleep(5)
            else:
                # 没出现复选框，可能在自动验证中
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
            
            # 立即检查盾
            handle_cloudflare(page)
            
            if "auth/login" not in page.url:
                log("✅ Cookie 登录成功！")
                return True
            log("Cookie 失效。")
        except:
            pass

    # 2. 账号密码登录
    if not HIDENCLOUD_EMAIL or not HIDENCLOUD_PASSWORD:
        return False

    log("尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        
        page.fill('input[name="email"]', HIDENCLOUD_EMAIL)
        page.fill('input[name="password"]', HIDENCLOUD_PASSWORD)
        
        time.sleep(0.5)
        # 点击前再查一次盾
        handle_cloudflare(page)
        
        page.click('button[type="submit"]')
        
        # 提交后等待
        time.sleep(3)
        handle_cloudflare(page)
        
        # 等待跳转
        page.wait_for_url(f"{BASE_URL}/*", timeout=30000)
        
        if "auth/login" in page.url:
             log("❌ 登录失败，可能停留在登录页。")
             return False

        log("✅ 账号密码登录成功！")
        return True
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        page.screenshot(path="login_fail.png")
        return False

def renew_service(page):
    try:
        log("进入续费流程...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        # 确保盾已过
        handle_cloudflare(page)

        log("点击 'Renew'...")
        # 强制等待元素出现，避免报错
        renew_btn = page.locator('button:has-text("Renew")')
        renew_btn.wait_for(state="visible", timeout=30000)
        renew_btn.click()
        
        # 点击后给予缓冲
        time.sleep(2)

        log("查找 'Create Invoice'...")
        create_btn = page.locator('button:has-text("Create Invoice")')
        create_btn.wait_for(state="visible", timeout=30000)
        
        # 关键时刻：点击前再次确认没有盾挡着
        handle_cloudflare(page)
        
        log("点击 'Create Invoice'...")
        create_btn.click()
        
        # --- 监控发票跳转 ---
        log("等待发票生成...")
        new_invoice_url = None
        
        # 增加等待时间到 90秒
        start_wait = time.time()
        while time.time() - start_wait < 90:
            
            # 1. 成功跳转检测
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面已跳转: {new_invoice_url}")
                break
            
            # 2. 盾检测
            # 点击 Create Invoice 后极易出盾，必须持续监控
            if page.locator('iframe[src*="challenges.cloudflare.com"]').count() > 0:
                log("⚠️ 遇到拦截，尝试处理...")
                handle_cloudflare(page)
            
            # 3. 检查是否还在当前页
            # 有时候点击没反应，可以尝试再次点击吗？风险较大，暂时只等待
            
            time.sleep(1)
        
        if not new_invoice_url:
            log("❌ 未能进入发票页面，超时。")
            page.screenshot(path="renew_stuck_chrome.png")
            return False

        # 确保在发票页
        if page.url != new_invoice_url:
            page.goto(new_invoice_url)
            
        handle_cloudflare(page) # 发票页检查

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
            
            # 使用官方 Chrome，并配置真实的 Linux User-Agent
            # 这能解决 "Windows UA on Linux OS" 的致命指纹矛盾
            browser = p.chromium.launch(
                channel="chrome", # 指定使用 Google Chrome stable
                headless=False,
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                ]
            )
            
            context = browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                # 使用标准的 Linux Chrome User Agent
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
