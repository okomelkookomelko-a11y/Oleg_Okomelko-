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
    await page.add_init_script(
        "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
    )


async def main():
    cfg = load_config()
    first  = cfg["first_name"]
    last   = cfg["last_name"]
    user   = cfg["username"]
    pwd    = cfg["password"]
    phone  = cfg["phone"]

    write_status("start", "Запускаємо браузер... v2-warmup")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()
        await apply_stealth(page)

        # ── Step 1: warm up (mimic pw_test.py which works) ─────────────────
        write_status("warm_up", "Розігріваємо браузер на google.com...")
        try:
            await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30_000)
            print(f"[warm_up] title={await page.title()}", flush=True)
        except Exception as e:
            print(f"[warm_up] WARN: {e}", flush=True)
        await asyncio.sleep(2)

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
        await asyncio.sleep(3)  # wait for page transition
        await page.screenshot(path=str(SS_DIR / "04_bday_init.png"))
        print(f"[fill_bday] url={page.url}", flush=True)

        # Dump full structure of the bday form including dropdown wrappers
        try:
            structure = await page.evaluate("""
                () => {
                    const ul = document.querySelector('ul[role="listbox"][aria-label="Month"]');
                    if (!ul) return 'NO_MONTH_UL';
                    const wrap = ul.closest('[jscontroller], [data-form-section], div');
                    const out = [];
                    let cur = ul.parentElement;
                    let depth = 0;
                    while (cur && depth < 6) {
                        out.push({
                            depth, tag: cur.tagName,
                            classes: (cur.className||'').slice(0,80),
                            role: cur.getAttribute('role') || '',
                            ariaLabel: cur.getAttribute('aria-label') || '',
                            ariaHaspopup: cur.getAttribute('aria-haspopup') || '',
                            ariaExpanded: cur.getAttribute('aria-expanded') || '',
                            jsaction: (cur.getAttribute('jsaction')||'').slice(0,40),
                        });
                        cur = cur.parentElement;
                        depth++;
                    }
                    return out;
                }
            """)
            print(f"[fill_bday] MONTH_PARENTS: {structure}", flush=True)
            # Also dump siblings of the listbox
            siblings = await page.evaluate("""
                () => {
                    const ul = document.querySelector('ul[role="listbox"][aria-label="Month"]');
                    if (!ul) return 'NO_UL';
                    const parent = ul.parentElement;
                    return Array.from(parent.children).map(c => ({
                        tag: c.tagName, role: c.getAttribute('role')||'',
                        cls: (c.className||'').slice(0,60),
                        text: (c.textContent||'').slice(0,30),
                        ariaLabel: c.getAttribute('aria-label')||''
                    }));
                }
            """)
            print(f"[fill_bday] MONTH_SIBLINGS: {siblings}", flush=True)
        except Exception as e:
            print(f"[fill_bday] dump failed: {e}", flush=True)

        try:
            # Day, Year are normal <input type="tel">
            await page.fill('input#day', "15")
            await asyncio.sleep(0.3)
            await page.fill('input#year', "1990")
            await asyncio.sleep(0.3)

            # Material Design select: click the parent div of the listbox to open it
            # Structure: <div jsaction="JIbuQc..."><...><ul role="listbox" aria-label="Month">
            month_root = page.locator(
                'div:has(> div > div > div > div > ul[role="listbox"][aria-label="Month"])'
            ).first
            # Fallback: any ancestor div with jsaction containing rymPhb (the listbox jsname)
            try:
                await month_root.click(timeout=5000)
            except Exception:
                # Try alternative: find by listbox and click 5 levels up
                await page.evaluate("""
                    () => {
                        const ul = document.querySelector('ul[role="listbox"][aria-label="Month"]');
                        if (!ul) return;
                        let cur = ul.parentElement;
                        for (let i = 0; i < 5 && cur; i++) cur = cur.parentElement;
                        if (cur) cur.click();
                    }
                """)
            await asyncio.sleep(0.7)
            # Click January option
            try:
                await page.locator('li[role="option"]:has-text("January"):visible').first.click(timeout=5000)
            except Exception:
                await page.locator('ul[role="listbox"][aria-label="Month"] li[role="option"]').first.click()
            await asyncio.sleep(0.5)

            # Gender: same pattern
            try:
                gender_root = page.locator(
                    'div:has(> div > div > div > div > ul[role="listbox"][aria-label*="gender" i])'
                ).first
                try:
                    await gender_root.click(timeout=5000)
                except Exception:
                    await page.evaluate("""
                        () => {
                            const ul = document.querySelector('ul[role="listbox"][aria-label*="gender" i], ul[role="listbox"][aria-label*="Gender"]');
                            if (!ul) return;
                            let cur = ul.parentElement;
                            for (let i = 0; i < 5 && cur; i++) cur = cur.parentElement;
                            if (cur) cur.click();
                        }
                    """)
                await asyncio.sleep(0.7)
                try:
                    await page.locator('li[role="option"]:has-text("Female"):visible').first.click(timeout=3000)
                except Exception:
                    await page.locator('ul[role="listbox"][aria-label*="gender" i] li[role="option"]').nth(1).click()
                await asyncio.sleep(0.5)
            except Exception as ge:
                print(f"[fill_bday] gender skipped: {ge}", flush=True)

            await page.screenshot(path=str(SS_DIR / "04_bday_filled.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(3)
        except Exception as e:
            print(f"[fill_bday] ERROR: {e} — taking screenshot and stopping", flush=True)
            await page.screenshot(path=str(SS_DIR / "04_bday_err.png"))
            write_status("error", f"Birthday step failed: {str(e)[:200]}")
            await browser.close()
            return

        # ── Step 5: username ───────────────────────────────────────────────
        write_status("fill_user", "Вводимо логін...")
        await asyncio.sleep(2)
        await page.screenshot(path=str(SS_DIR / "05_user_init.png"))
        print(f"[fill_user] url={page.url}", flush=True)

        # Handle collectemailphone anti-bot gate
        if "collectemailphone" in page.url or "identifier" in page.url:
            print("[fill_user] collectemailphone gate detected — dumping elements", flush=True)
            try:
                all_elems = await page.evaluate("""
                    () => {
                        const els = document.querySelectorAll(
                            'a, button, input, div[role="button"], div[role="link"], span[role="link"]'
                        );
                        return Array.from(els).map(el => ({
                            tag: el.tagName,
                            type: el.type || '',
                            id: el.id || '',
                            name: el.name || '',
                            href: el.href || '',
                            role: el.getAttribute('role') || '',
                            text: (el.textContent || '').trim().slice(0, 80),
                            ariaLabel: el.getAttribute('aria-label') || '',
                        }));
                    }
                """)
                (BASE / "page_dump.json").write_text(
                    json.dumps(all_elems, indent=2, ensure_ascii=False)
                )
                print(f"[fill_user] dumped {len(all_elems)} elements to page_dump.json", flush=True)
            except Exception as de:
                print(f"[fill_user] dump error: {de}", flush=True)

            # Try "Create account" / "Створити акаунт" links on this page
            create_found = False
            for sel in [
                'button:has-text("Don\'t have an email address or phone number?")',
                'a:has-text("Create account")',
                'a:has-text("Створити акаунт")',
                'button:has-text("Create account")',
                'div[role="link"]:has-text("Create")',
                'a:has-text("Create a new account")',
                'span:has-text("Create account")',
            ]:
                try:
                    loc = page.locator(sel).first
                    if await loc.count() > 0:
                        await loc.click(timeout=5000)
                        create_found = True
                        print(f"[fill_user] clicked Create account via: {sel}", flush=True)
                        await asyncio.sleep(2)
                        break
                except Exception:
                    pass

            if not create_found:
                # Enter phone number to pass the gate (Google will SMS-verify then continue signup)
                print("[fill_user] no Create link — entering phone in emailPhone gate", flush=True)
                try:
                    await page.fill('input[name="emailPhone"], input#emailPhone', phone)
                    await asyncio.sleep(0.5)
                    await page.click('button:has-text("Далі"), button:has-text("Next")')
                    await asyncio.sleep(3)
                    await page.screenshot(path=str(SS_DIR / "05_after_phone_gate.png"))
                    print(f"[fill_user] after phone gate, url={page.url}", flush=True)
                except Exception as pe:
                    print(f"[fill_user] phone gate failed: {pe}", flush=True)

        # Modern Gmail shows suggested usernames first. Click "Create your own".
        try:
            create_own = page.locator(
                'div:has-text("Create your own Gmail address"), '
                'div:has-text("Створіть власну адресу"), '
                'div[role="radio"]:has-text("Create"), '
                'button:has-text("Create your own")'
            ).first
            if await create_own.count() > 0:
                await create_own.click(timeout=5000)
                await asyncio.sleep(1.5)
                print(f"[fill_user] clicked 'Create your own'", flush=True)
        except Exception as e:
            print(f"[fill_user] no 'Create own' option: {e}", flush=True)

        try:
            # Username may be hidden until "Create your own" radio is clicked
            await page.wait_for_selector('input[name="Username"]', state='attached', timeout=30_000)
            if not await page.locator('input[name="Username"]').is_visible():
                print("[fill_user] Username hidden — clicking Create own", flush=True)
                for csel in [
                    'div[role="radio"]:has-text("Create")',
                    'div[data-value="USERNAME"]',
                    'label:has-text("Create")',
                    'div:has-text("Create your own Gmail")',
                ]:
                    try:
                        cl = page.locator(csel).first
                        if await cl.count() > 0:
                            await cl.click(timeout=3000)
                            await asyncio.sleep(1.5)
                            if await page.locator('input[name="Username"]').is_visible():
                                print(f"[fill_user] visible after: {csel}", flush=True)
                                break
                    except Exception:
                        pass
                if not await page.locator('input[name="Username"]').is_visible():
                    print("[fill_user] JS unhide Username", flush=True)
                    await page.evaluate("""
                        () => {
                            const inp = document.querySelector('input[name="Username"]');
                            if (!inp) return;
                            let p = inp;
                            for (let k = 0; k < 10; k++) {
                                p = p.parentElement;
                                if (!p) break;
                                p.style.display = '';
                                p.style.visibility = '';
                                p.style.opacity = '1';
                                p.removeAttribute('hidden');
                                p.removeAttribute('aria-hidden');
                            }
                            inp.style.display = '';
                            inp.style.visibility = '';
                            inp.style.opacity = '1';
                            inp.removeAttribute('hidden');
                            inp.focus();
                        }
                    """)
                    await asyncio.sleep(0.5)
            await page.screenshot(path=str(SS_DIR / "05_before_fill.png"))
            print(f"[fill_user] visible={await page.locator('input[name=\"Username\"]').is_visible()}", flush=True)
            # Use force=True to bypass Playwright visibility check if still hidden
            try:
                await page.locator('input[name="Username"]').fill(user, force=True)
            except Exception as fe:
                print(f"[fill_user] force fill failed: {fe}, trying JS setValue", flush=True)
                await page.evaluate("""
                    (v) => {
                        const inp = document.querySelector('input[name="Username"]');
                        if (!inp) return;
                        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, v);
                        inp.dispatchEvent(new Event('input', {bubbles: true}));
                        inp.dispatchEvent(new Event('change', {bubbles: true}));
                    }
                """, user)
            await asyncio.sleep(1)
            await page.screenshot(path=str(SS_DIR / "05_username.png"))
            await page.click('button:has-text("Далі"), button:has-text("Next")')
            await asyncio.sleep(3)
        except Exception as e:
            write_status("error", f"Помилка при вводі логіну: {e}")
            # Dump form fields for diagnosis
            try:
                fields = await page.evaluate("""
                    () => Array.from(document.querySelectorAll('input,button,div[role="radio"],div[role="button"]'))
                        .slice(0, 25).map(el => ({
                            tag: el.tagName, type: el.type||'', id: el.id||'',
                            name: el.name||'', role: el.getAttribute('role')||'',
                            text: (el.textContent||'').slice(0,50),
                            ariaLabel: el.getAttribute('aria-label')||''
                        }))
                """)
                print(f"[fill_user] FIELDS: {fields}", flush=True)
            except Exception:
                pass
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
