import os
import time
import sys
import random
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

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

def manual_stealth(page):
    """
    手动注入反指纹脚本，不依赖外部库。
    移除 navigator.webdriver 标记，防止被 Cloudflare 识别为机器人。
    """
    page.add_init_script("""
        // 1. 覆盖 webdriver 属性
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // 2. 伪造 Chrome 运行环境
        window.chrome = {
            runtime: {}
        };

        // 3. 伪造插件列表 (Headless 模式下通常为空)
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });

        // 4. 伪造语言设置
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en']
        });
    """)

def handle_cloudflare(page):
    """
    XVFB 环境下的 Cloudflare 处理逻辑。
    """
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    # 快速检查
    if page.locator(iframe_selector).count() == 0:
        return True

    log("⚠️ 检测到 Cloudflare 验证，开始对抗...")
    start_time = time.time()
    
    # 最多尝试 45 秒
    while time.time() - start_time < 45:
        try:
            # 检查是否通过
            if page.locator(iframe_selector).count() == 0:
                log("✅ Cloudflare 验证已通过！")
                return True

            frame = page.frame_locator(iframe_selector)
            checkbox = frame.locator('input[type="checkbox"]')
            
            if checkbox.is_visible():
                box = checkbox.bounding_box()
                if box:
                    log("定位到验证框，执行拟人移动点击...")
                    # 模拟人类鼠标抖动
                    x = box['x'] + box['width'] / 2 + random.uniform(-5, 5)
                    y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
                    page.mouse.move(x, y, steps=10)
                    time.sleep(random.uniform(0.1, 0.3))
                    page.mouse.down()
                    time.sleep(random.uniform(0.1, 0.2))
                    page.mouse.up()
                else:
                    checkbox.click()
                
                log("已点击，等待响应...")
                time.sleep(5)
            else:
                # 验证框存在但复选框还没出来，可能在加载
                time.sleep(1)

        except Exception as e:
            # 忽略过程错误
            pass
            
        time.sleep(1)

    log("❌ Cloudflare 验证超时。")
    return False

def login(page):
    log("开始登录流程...")
    
    # Cookie 登录尝试
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
            log("Cookie 失效，转为密码登录。")
            page.context.clear_cookies()
        except Exception as e:
            log(f"Cookie 登录出错: {e}")

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
        log("开始续费...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        handle_cloudflare(page)

        log("点击 'Renew'...")
        page.locator('button:has-text("Renew")').click()
        time.sleep(2)

        log("点击 'Create Invoice'...")
        create_btn = page.locator('button:has-text("Create Invoice")')
        create_btn.wait_for(state="visible", timeout=10000)
        
        # 预判拦截
        handle_cloudflare(page)
        create_btn.click()
        
        log("等待发票生成...")
        new_invoice_url = None
        
        # 等待循环
        for i in range(40):
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log(f"🎉 页面跳转成功: {new_invoice_url}")
                break
            
            # 持续监控 Cloudflare
            handle_cloudflare(page)
            time.sleep(1)
            
        if not new_invoice_url:
            log("❌ 未能获取发票 URL，截图保存。")
            page.screenshot(path="renew_stuck.png")
            return False

        if page.url != new_invoice_url:
            page.goto(new_invoice_url)

        log("点击 'Pay'...")
        # 确保 Pay 按钮可见再点击
        pay_btn = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_btn.wait_for(state="visible", timeout=30000)
        pay_btn.click()
        
        log("✅ 续费动作触发完成。")
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
            log("启动浏览器 (Headless=False + XVFB)...")
            # 必须使用 headless=False 以配合 XVFB
            browser = p.chromium.launch(
                headless=False,
                args=['--no-sandbox', '--disable-blink-features=AutomationControlled']
            )
            context = browser.new_context(viewport={'width': 1280, 'height': 960})
            page = context.new_page()
            
            # 注入隐身代码
            manual_stealth(page)

            if not login(page):
                sys.exit(1)

            if not renew_service(page):
                sys.exit(1)

            log("🎉 任务全部完成！")
        except Exception as e:
            log(f"💥 严重错误: {e}")
            if 'page' in locals() and page:
                page.screenshot(path="fatal_error.png")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
