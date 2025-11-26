import os
import time
import sys
import random
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

# --- 全局配置 ---
HIDENCLOUD_COOKIE = os.environ.get('HIDENCLOUD_COOKIE')
HIDENCLOUD_EMAIL = os.environ.get('HIDENCLOUD_EMAIL')
HIDENCLOUD_PASSWORD = os.environ.get('HIDENCLOUD_PASSWORD')

# 目标网页 URL
BASE_URL = "https://dash.hidencloud.com"
LOGIN_URL = f"{BASE_URL}/auth/login"
SERVICE_URL = f"{BASE_URL}/service/71879/manage"

# Cookie 名称
COOKIE_NAME = "remember_web_59ba36addc2b2f9401580f014c7f58ea4e30989d"

def log(message):
    """打印带时间戳的日志"""
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)

def stealth_mode(page):
    """隐藏自动化特征，防止被 Cloudflare 轻易识别"""
    try:
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)
    except Exception:
        pass

def handle_cloudflare(page):
    """
    暴力处理 Cloudflare 验证。
    使用 while 循环持续检测，直到验证框消失。
    """
    # 定位 Cloudflare iframe
    iframe_selector = 'iframe[src*="challenges.cloudflare.com"]'
    
    # 最多尝试处理 60 秒
    start_time = time.time()
    
    while time.time() - start_time < 60:
        # 如果找不到 iframe，说明可能已经通过了或者没有验证
        if page.locator(iframe_selector).count() == 0:
            return True

        try:
            log("⚠️ 检测到 Cloudflare 验证，尝试模拟人类操作...")
            
            # 获取 iframe
            frame = page.frame_locator(iframe_selector)
            # 获取点击目标（通常是一个 checkbox 或者 iframe 的 body）
            # 优先尝试找 checkbox，如果找不到就点 body
            target = frame.locator('input[type="checkbox"]')
            if not target.is_visible():
                target = frame.locator('body')
            
            # 获取元素的位置
            box = target.bounding_box()
            if box:
                # --- 模拟人类鼠标移动 ---
                # 移动到元素中心附近（加一点随机偏移）
                x = box['x'] + box['width'] / 2 + random.uniform(-5, 5)
                y = box['y'] + box['height'] / 2 + random.uniform(-5, 5)
                
                log(f"移动鼠标至 ({int(x)}, {int(y)})...")
                page.mouse.move(x, y, steps=15) # steps 越大移动越慢
                time.sleep(random.uniform(0.3, 0.7)) # 犹豫一下
                
                log("点击验证框...")
                page.mouse.down()
                time.sleep(random.uniform(0.1, 0.3)) # 按下持续时间
                page.mouse.up()
            else:
                log("无法获取验证框坐标，尝试直接点击...")
                target.click()

            # 点击后等待一会儿，看是否通过
            log("点击完成，等待验证结果...")
            # 检查 iframe 是否消失
            try:
                page.wait_for_selector(iframe_selector, state='detached', timeout=5000)
                log("✅ Cloudflare 验证框已消失（验证通过）！")
                return True
            except:
                log("⏳ 验证框仍在，准备重试...")
                time.sleep(2)
                
        except Exception as e:
            log(f"处理验证时发生小错误（将重试）: {e}")
            time.sleep(2)
    
    log("❌ Cloudflare 验证处理超时（60秒）。")
    return False

def login(page):
    """处理登录逻辑"""
    log("开始登录流程...")
    stealth_mode(page) # 开启隐身模式

    # --- 方案一：Cookie 登录 ---
    if HIDENCLOUD_COOKIE:
        log("检测到 HIDENCLOUD_COOKIE，尝试使用 Cookie 登录。")
        try:
            page.context.add_cookies([{
                'name': COOKIE_NAME, 'value': HIDENCLOUD_COOKIE,
                'domain': 'dash.hidencloud.com', 'path': '/',
                'expires': int(time.time()) + 3600 * 24 * 365,
                'httpOnly': True, 'secure': True, 'sameSite': 'Lax'
            }])
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
            
            # 检查验证
            handle_cloudflare(page)
            # 等待页面稳定
            page.wait_for_load_state("networkidle")

            if "auth/login" in page.url:
                log("Cookie 登录失效，回退到账号密码。")
                page.context.clear_cookies()
            else:
                log("✅ Cookie 登录成功！")
                return True
        except Exception as e:
            log(f"Cookie 登录出错: {e}")
            page.context.clear_cookies()

    # --- 方案二：账号密码登录 ---
    if not HIDENCLOUD_EMAIL or not HIDENCLOUD_PASSWORD:
        return False

    log("尝试账号密码登录...")
    try:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
        handle_cloudflare(page) # 页面加载后立即检查验证
        
        log("填写账号密码...")
        page.fill('input[name="email"]', HIDENCLOUD_EMAIL)
        page.fill('input[name="password"]', HIDENCLOUD_PASSWORD)
        
        handle_cloudflare(page) # 点击登录前再检查一次

        page.click('button[type="submit"]:has-text("Sign in to your account")')
        
        # 处理登录后的潜在验证
        if handle_cloudflare(page):
             # 如果处理了验证，等待跳转
             page.wait_for_url(f"{BASE_URL}/dashboard", timeout=60000)
        else:
             page.wait_for_url(f"{BASE_URL}/dashboard", timeout=60000)

        if "auth/login" in page.url:
            log("❌ 登录失败。")
            page.screenshot(path="login_failure.png")
            return False

        log("✅ 登录成功！")
        return True
    except Exception as e:
        log(f"❌ 登录异常: {e}")
        page.screenshot(path="login_error.png")
        return False

def renew_service(page):
    """执行续费流程"""
    try:
        log("开始续费...")
        if page.url != SERVICE_URL:
            page.goto(SERVICE_URL, wait_until="domcontentloaded", timeout=60000)
        
        handle_cloudflare(page)
        page.wait_for_load_state("networkidle")

        log("查找 'Renew' 按钮...")
        renew_button = page.locator('button:has-text("Renew")')
        renew_button.wait_for(state="visible", timeout=30000)
        renew_button.click()
        log("✅ 点击 'Renew'。")
        
        time.sleep(1)

        log("准备捕获发票链接...")
        new_invoice_url = None
        def handle_response(response):
            nonlocal new_invoice_url
            if "/payment/invoice/" in response.url:
                new_invoice_url = response.url

        page.on("response", handle_response)
        
        # 点击 Create Invoice
        create_invoice_button = page.locator('button:has-text("Create Invoice")')
        create_invoice_button.wait_for(state="visible", timeout=30000)
        
        # 有时候点击会被 Cloudflare 挡住，这里做个预判
        handle_cloudflare(page)
        create_invoice_button.click()
        log("✅ 点击 'Create Invoice'。")

        # --- 核心等待循环 ---
        log("正在等待发票生成 (含 Cloudflare 监控)...")
        timeout = 40 # 增加超时时间
        start_wait = time.time()
        
        while time.time() - start_wait < timeout:
            # 1. 检查是否捕获到 URL
            if new_invoice_url:
                log(f"🎉 捕获到 URL: {new_invoice_url}")
                break
            
            # 2. 检查是否直接跳转
            if "/payment/invoice/" in page.url:
                new_invoice_url = page.url
                log("🎉 页面已跳转到发票页。")
                break
            
            # 3. 重点：持续处理 Cloudflare
            # 如果这里处理成功了，下一次循环通常就能拿到 URL 或跳转
            handle_cloudflare(page)
            
            time.sleep(1)
        
        page.remove_listener("response", handle_response)
        
        if new_invoice_url:
            if page.url != new_invoice_url:
                 page.goto(new_invoice_url, wait_until="domcontentloaded")
            handle_cloudflare(page) # 发票页面可能也有验证
        else:
            log("❌ 未获取到发票 URL。")
            page.screenshot(path="renew_failed.png")
            return False

        log("查找 'Pay' 按钮...")
        pay_button = page.locator('a:has-text("Pay"):visible, button:has-text("Pay"):visible').first
        pay_button.wait_for(state="visible", timeout=20000)
        pay_button.click()
        log("✅ 'Pay' 按钮已点击。")
        
        time.sleep(5)
        log("续费流程结束。")
        page.screenshot(path="renew_success.png")
        return True
    except Exception as e:
        log(f"❌ 续费错误: {e}")
        page.screenshot(path="renew_error.png")
        return False

def main():
    if not HIDENCLOUD_COOKIE and not (HIDENCLOUD_EMAIL and HIDENCLOUD_PASSWORD):
        log("❌ 缺少配置。")
        sys.exit(1)

    with sync_playwright() as p:
        try:
            log("启动浏览器...")
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-infobars',
                    '--window-size=1920,1080',
                    '--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                ]
            )
            # 设置较大的视口，有些验证码在小窗口下会加载失败
            context = browser.new_context(viewport={'width': 1920, 'height': 1080})
            page = context.new_page()

            if not login(page):
                sys.exit(1)

            if not renew_service(page):
                sys.exit(1)

            log("🎉 任务完成！")
        except Exception as e:
            log(f"💥 严重错误: {e}")
            sys.exit(1)
        finally:
            if 'browser' in locals() and browser:
                browser.close()

if __name__ == "__main__":
    main()
