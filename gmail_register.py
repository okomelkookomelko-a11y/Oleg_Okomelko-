"""
Gmail registration via Playwright with stealth.
Reads config from gmail_config.json, writes progress to gmail_status.json,
screenshots to screenshots/, waits for SMS code in sms_code.txt.
"""
import asyncio, json, sys, time, os
from pathlib import Path
from playwright.async_api import async_playwright, TimeoutError as PWTimeout

BASE = Path(__file__).parent
CFG  = BASE / "gmail_config.json"
STATUS = BASE / "gmail_status.json"
SMS_FILE = BASE / "sms_code.txt"
SS_DIR = BASE / "screenshots"
SS_DIR.mkdir(exist_ok=True)


def write_status(step: str, message: str, waiting: bool = False):
    STATUS.write_text(json.dumps({"step": step, "message": message, "waiting": waiting},
                                 ensure_ascii=False, indent=2))
    print(f"[{step}] {message}", flush=True)


def load_config():
    if not CFG.exists():
        print("ERROR: gmail_config.json not found", flush=True)
        sys.exit(1)
    return json.loads(CFG.read_text())


async def wait_for_sms(timeout_s=300) -> str:
    """Poll sms_code.txt for up to timeout_s seconds."""
    SMS_FILE.unlink(missing_ok=True)
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if SMS_FILE.exists():
            code = SMS_FILE.read_text().strip()
            if code:
                SMS_FILE.unlink(missing_ok=True)
                return code
        await asyncio.sleep(3)
    return ""


async def apply_stealth(page):
    """Minimal stealth patches without external dependency."""
    await page.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3]});
        Object.defineProperty(navigator, 'languages', {get: () => ['uk-UA', 'uk', 'en-US']});
        window.chrome = {runtime: {}};
    """)


async def main():
    cfg = load_config()
    first  = cfg["first_name"]
    last   = cfg["last_name"]
    user   = cfg["username"]
    pwd    = cfg["password"]
    phone  = cfg["phone"]

    write_status("start", "Запускаємо браузер...")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--disable-infobars",
                "--window-size=1280,800",
                "--lang=uk-UA",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="uk-UA",
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            timezone_id="Europe/Kyiv",
        )
        page = await context.new_page()
        await apply_stealth(page)

        # Catch and log any page errors
        page.on("pageerror", lambda e: print(f"[PAGE_ERROR] {e}", flush=True))
        page.on("console",   lambda m: print(f"[CONSOLE:{m.type}] {m.text[:120]}", flush=True)
                             if m.type in ("error", "warning") else None)

        # ── Step 1: warm up with google.com first ──────────────────────────
        write_status("warm_up", "Відкриваємо google.com...")
        try:
            await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30_000)
            await page.screenshot(path=str(SS_DIR / "01_google.png"))
            print(f"[warm_up] title={await page.title()}", flush=True)
            await asyncio.sleep(2)
        except Exception as e:
            print(f"[warm_up] WARN: {e}", flush=True)

        # ── Step 2: navigate to signup ─────────────────────────────────────
        write_status("open", "Відкриваємо реєстрацію Gmail...")
        signup_url = (
            "https://accounts.google.com/signup/v2/webcreateaccount"
            "?flowName=GlifWebSignIn&flowEntry=SignUp"
        )
        try:
            resp = await page.goto(signup_url, wait_until="commit", timeout=45_000)
            print(f"[open] status={resp.status if resp else 'n/a'} url={page.url}", flush=True)
            await asyncio.sleep(3)
            await page.screenshot(path=str(SS_DIR / "02_signup.png"))
            title = await page.title()
            print(f"[open] title={title}", flush=True)
        except PWTimeout:
            write_status("error", "Тайм-аут при завантаженні сторінки реєстрації")
            await page.screenshot(path=str(SS_DIR / "02_timeout.png"))
            await browser.close()
            return
        except Exception as e:
            write_status("error", f"Помилка: {e}")
            await page.screenshot(path=str(SS_DIR / "02_error.png"))
            await browser.close()
            return

        # Check if we got redirected away (Google blocking)
        if "accounts.google.com" not in page.url:
            write_status("error", f"Перенаправлено: {page.url}")
            await browser.close()
            return

        # ── Step 3: fill first/last name ───────────────────────────────────
        write_status("fill_name", "Заповнюємо ім'я...")
        try:
            await page.wait_for_selector('input[name="firstName"]', timeout=20_000)
            await asyncio.sleep(1)
            await page.fill('input[name="firstName"]', first)
            await asyncio.sleep(0.5)
            await page.fill('input[name="lastName"]',  last)
            await asyncio.sleep(1)
            await page.screenshot(path=str(SS_DIR / "03_name.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(2)
        except PWTimeout:
            write_status("error", "Не знайдено поле firstName")
            await page.screenshot(path=str(SS_DIR / "03_no_firstname.png"))
            print(f"[fill_name] current url: {page.url}", flush=True)
            html_len = len(await page.content())
            print(f"[fill_name] page html length: {html_len}", flush=True)
            await browser.close()
            return

        # ── Step 4: birthday + gender ──────────────────────────────────────
        write_status("fill_bday", "День народження...")
        try:
            await page.wait_for_selector('input[name="month"], #month', timeout=10_000)
            # Try select dropdowns or input fields
            for sel, val in [
                ('select#month, input[name="month"]', "1"),
                ('input[name="day"]', "15"),
                ('input[name="year"]', "1990"),
            ]:
                el = page.locator(sel).first
                tag = await el.evaluate("e => e.tagName")
                if tag == "SELECT":
                    await el.select_option(val)
                else:
                    await el.fill(val)
                await asyncio.sleep(0.3)
            # Gender
            gender_sel = page.locator('select#gender, select[name="gender"]').first
            await gender_sel.select_option("1")  # Female or first option
            await asyncio.sleep(1)
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(2)
            await page.screenshot(path=str(SS_DIR / "04_bday.png"))
        except Exception as e:
            print(f"[fill_bday] WARN: {e} — skipping", flush=True)
            await page.screenshot(path=str(SS_DIR / "04_bday_err.png"))

        # ── Step 5: username ───────────────────────────────────────────────
        write_status("fill_user", "Вводимо логін...")
        try:
            await page.wait_for_selector('input[name="Username"]', timeout=15_000)
            await page.fill('input[name="Username"]', user)
            await asyncio.sleep(1)
            await page.screenshot(path=str(SS_DIR / "05_username.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(3)
        except Exception as e:
            write_status("error", f"Помилка при вводі логіну: {e}")
            await page.screenshot(path=str(SS_DIR / "05_user_err.png"))
            await browser.close()
            return

        # ── Step 6: password ───────────────────────────────────────────────
        write_status("fill_pass", "Вводимо пароль...")
        try:
            await page.wait_for_selector('input[name="Passwd"]', timeout=15_000)
            await page.fill('input[name="Passwd"]',       pwd)
            await page.fill('input[name="PasswdAgain"]',  pwd)
            await asyncio.sleep(1)
            await page.screenshot(path=str(SS_DIR / "06_pass.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(3)
        except Exception as e:
            write_status("error", f"Помилка при вводі паролю: {e}")
            await page.screenshot(path=str(SS_DIR / "06_pass_err.png"))
            await browser.close()
            return

        # ── Step 7: phone number ───────────────────────────────────────────
        write_status("fill_phone", "Вводимо номер телефону...")
        try:
            await page.wait_for_selector('input[name="phoneNumberId"]', timeout=15_000)
            await page.fill('input[name="phoneNumberId"]', phone)
            await asyncio.sleep(1)
            await page.screenshot(path=str(SS_DIR / "07_phone.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(5)
        except Exception as e:
            write_status("error", f"Помилка при вводі телефону: {e}")
            await page.screenshot(path=str(SS_DIR / "07_phone_err.png"))
            await browser.close()
            return

        await page.screenshot(path=str(SS_DIR / "08_after_phone.png"))

        # ── Step 8: wait for SMS code ──────────────────────────────────────
        write_status("wait_sms", f"Введіть SMS-код у файл {SMS_FILE.name}", waiting=True)
        code = await wait_for_sms(300)
        if not code:
            write_status("error", "SMS-код не отримано протягом 5 хвилин")
            await browser.close()
            return

        # ── Step 9: enter SMS code ─────────────────────────────────────────
        write_status("fill_sms", f"Вводимо SMS-код {code}...")
        try:
            await page.wait_for_selector('input[name="code"]', timeout=15_000)
            await page.fill('input[name="code"]', code)
            await asyncio.sleep(1)
            await page.click('button:has-text("Підтвердити"), button:has-text("Verify")')
            await asyncio.sleep(5)
            await page.screenshot(path=str(SS_DIR / "09_sms.png"))
        except Exception as e:
            write_status("error", f"Помилка при введенні SMS: {e}")
            await browser.close()
            return

        # ── Step 10: accept ToS ────────────────────────────────────────────
        write_status("accept_tos", "Приймаємо умови...")
        try:
            await page.click('button:has-text("Погоджуюся"), button:has-text("I agree")',
                             timeout=10_000)
            await asyncio.sleep(3)
        except Exception:
            pass  # ToS page might not appear

        await page.screenshot(path=str(SS_DIR / "10_done.png"))
        final_url = page.url
        print(f"[done] final url: {final_url}", flush=True)

        if "myaccount.google.com" in final_url or "mail.google.com" in final_url:
            write_status("done", f"✅ Акаунт {user}@gmail.com успішно створено!")
        else:
            write_status("done", f"Завершено (перевірте скрін 10_done.png). URL: {final_url}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
