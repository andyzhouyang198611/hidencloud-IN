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

# 基础反指纹 JS (去掉了容易出错的复杂部分)
STEALTH_JS = """
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    window.chrome = { runtime: {} };
    Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
"""

def handle_cloudflare(page):
    """
    策略：如果遇到验证码，尝试点击。如果卡住超过 10 秒，直接刷新页面重试。
    """
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    # 总共尝试 120 秒
    start_time = time.time()
    while time.time() - start_time < 120:
        
        # 1. 检查验证框是否存在
        if page.locator(iframe_selector).count() == 0:
            return True # 验证框不存在，说明已通过或无需验证

        log("⚠️ 检测到 Cloudflare 验证...")

        try:
            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            spinner = frame.locator('#spinner') # 加载圈
            
            # 如果复选框可见，点击它
            if checkbox.is_visible():
                log("点击验证复选框...")
                # 稍微随机延迟
                time.sleep(random.uniform(0.5, 1.5))
                checkbox.click()
                log("已点击，等待响应...")
                
                # 点击后等待 8 秒
                for _ in range(8):
                    time.sleep(1)
                    if page.locator(iframe_selector).count() == 0:
                        log("✅ 验证通过！")
                        return True
            
            # 如果此时验证框还在，说明可能卡住了 (Validating security... 转圈不消失)
            log("⏳ 验证似乎卡住了，准备刷新页面重试...")
            
            # 截图记录一下卡住的状态
            # page.screenshot(path=f"cf_stuck_{int(time.time())}.png")
            
            # 刷新页面！这是破局的关键
            page.reload(wait_until="domcontentloaded")
            log("🔄 页面已刷新，等待重新加载...")
            
            # 重新注入 JS (因为刷新后失效)
            page.add_init_script(STEALTH_JS)
            
            # 等待页面稳定，进入下一次循环
            time.sleep(5)

        except Exception as e:
            log(f"处理验证时发生错误: {e}")
            time.sleep(2)
            
    log("❌ Cloudflare 验证最终超时。")
    return False

def login(page):
    log("开始登录流程...")
    
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
            
            # 检查盾
            handle_cloudflare(page)
            
            if "auth/login" not in page.url:
                log("✅ Cookie 登录成功！")
                return True
            log("Cookie 失效。")
        except:
            pass

    if not HIDENCLOUD_EMAIL or not HIDENCLOUD_PASSWORD:
        return False

    log("尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page)
        
        page.fill('input[name="email"]', HIDENCLOUD_EMAIL)
        page.fill('input[name="password"]', HIDENCLOUD_PASSWORD)
        
        handle_cloudflare(page)
        page.click('button[type="submit"]:has-text("Sign in to your account")')
        
        # 登录后等待
        time.sleep(3)
        handle_cloudflare(page)
        
        page.wait_for_url(f"{BASE_URL}/dashboard", timeout=60000)
        log("✅ 账号密码登录成功！")
        return True
    except Exception as e:
        log(f"❌ 登录失败: {e}")
        page.screenshot(path="login_fail.png")
        return False

def renew_service(page):
    try:
        log("进入续费流程...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        if not handle_cloudflare(page):
             raise Exception("Cloudflare 验证未通过")

        log("点击 'Renew'...")
        page.locator('button:has-text("Renew")').click()
        time.sleep(2)

        log("点击 'Create Invoice'...")
        create_btn = page.locator('button:has-text("Create Invoice")')
        create_btn.wait_for(state="visible", timeout=10000)
        
        # 预先处理可能弹出的验证
        handle_cloudflare(page)
        
        create_btn.click()
        log("已点击 'Create Invoice'，开始监控...")

        # --- 监控与刷新逻辑 ---
        new_invoice_url = None
        
        # 循环检查
        for i in range(20): # 约 40-60秒
            # 1. 成功跳转?
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面已跳转: {new_invoice_url}")
                break
            
            # 2. 检查是否有盾，如果有盾且卡住，handle_cloudflare 内部会刷新
            # 注意：如果在这里刷新了，意味着页面会重载，可能需要重新点击按钮吗？
            # 这是一个风险点。但在发票生成页，通常刷新后会停留在当前页或跳转。
            # 如果是在点击按钮后立即出盾，刷新可能会导致按钮点击失效，需要重新点。
            # 为了简单起见，这里我们只做简单的盾处理，不强制刷新，除非万不得已。
            
            iframe_count = page.locator('iframe[src*="challenges.cloudflare.com"]').count()
            if iframe_count > 0:
                log("⚠️ 生成发票时遇到拦截，尝试处理...")
                handle_cloudflare(page) # 这里面有刷新逻辑
                
                # 如果刷新了，页面状态变了，我们需要检查是否还在原来的页面
                if page.url == SERVICE_URL:
                    log("🔄 页面刷新后回到了服务页，尝试重新点击 'Create Invoice'...")
                    if create_btn.is_visible():
                        create_btn.click()
                elif "/payment/invoice/" in page.url:
                    new_invoice_url = page.url
                    break

            time.sleep(2)

        if not new_invoice_url and "/payment/invoice/" not in page.url:
            log("❌ 未能进入发票页面。")
            page.screenshot(path="renew_stuck.png")
            return False

        # 确保在发票页
        if new_invoice_url and page.url != new_invoice_url:
            page.goto(new_invoice_url)

        handle_cloudflare(page) # 发票页再查一次

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
            log("启动浏览器...")
            # 移除所有自定义 User-Agent，使用默认值以避免指纹冲突
            browser = p.chromium.launch(
                headless=False, # 配合 XVFB
                args=[
                    '--no-sandbox',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--window-size=1920,1080'
                ]
            )
            # 不设置 viewport 和 user_agent，让其自动适配
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
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
