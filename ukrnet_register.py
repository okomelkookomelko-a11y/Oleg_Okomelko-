#!/usr/bin/env python3
"""
ukr.net account registration automation via Playwright.
Config from /home/bot/my-bot/ukrnet_config.json:
  { "login": "...", "password": "...", "first_name": "...", "last_name": "..." }
Status written to /home/bot/my-bot/ukrnet_status.json.
"""
import asyncio, json, os, time
from pathlib import Path
from playwright.async_api import async_playwright

CONFIG_FILE = Path("/home/bot/my-bot/ukrnet_config.json")
STATUS_FILE = Path("/home/bot/my-bot/ukrnet_status.json")
LOG_FILE    = Path("/home/bot/my-bot/ukrnet_register.log")

SIGNUP_URL = "https://account.ukr.net/register"


def write_status(status: str, message: str = ""):
    STATUS_FILE.write_text(json.dumps({"status": status, "message": message,
                                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")},
                                       ensure_ascii=False, indent=2))
    print(f"[status] {status}: {message}", flush=True)


def load_config():
    if not CONFIG_FILE.exists():
        return {"login": "logasst77143", "password": "LogBot2026!",
                "first_name": "Logistics", "last_name": "ASSISTANCE"}
    return json.loads(CONFIG_FILE.read_text())


async def dump_page(page, label: str):
    info = await page.evaluate("""() => ({
        url: location.href,
        title: document.title,
        inputs: [...document.querySelectorAll('input')].map(e => ({
            name: e.name, id: e.id, type: e.type, placeholder: e.placeholder,
            value: e.value.slice(0, 40), visible: e.offsetParent !== null
        })),
        buttons: [...document.querySelectorAll('button,input[type=submit]')].map(e => ({
            tag: e.tagName, type: e.type || '', text: (e.textContent||e.value||'').trim().slice(0, 60),
            visible: e.offsetParent !== null
        })),
        text_snippet: document.body.innerText.slice(0, 400)
    })""")
    print(f"[dump:{label}] url={info['url']}", flush=True)
    print(f"[dump:{label}] title={info['title']}", flush=True)
    print(f"[dump:{label}] inputs={json.dumps(info['inputs'], ensure_ascii=False)}", flush=True)
    print(f"[dump:{label}] buttons={json.dumps(info['buttons'], ensure_ascii=False)}", flush=True)
    print(f"[dump:{label}] text={info['text_snippet'][:300]}", flush=True)
    return info


async def js_fill(page, selector: str, value: str):
    """Fill React/managed inputs via native setter trick."""
    await page.evaluate(f"""(sel, val) => {{
        const el = document.querySelector(sel);
        if (!el) return false;
        const nativeSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        nativeSetter.call(el, val);
        el.dispatchEvent(new Event('input', {{bubbles: true}}));
        el.dispatchEvent(new Event('change', {{bubbles: true}}));
        return true;
    }}""", selector, value)


async def main():
    cfg = load_config()
    login    = cfg["login"]
    password = cfg["password"]
    fname    = cfg.get("first_name", "Logistics")
    lname    = cfg.get("last_name", "ASSISTANCE")

    print(f"[start] ukrnet_register.py — login={login}", flush=True)
    write_status("starting")

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 800},
            locale="uk-UA",
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        )
        page = await ctx.new_page()

        # --- Step 1: open signup page ---
        print(f"[open] {SIGNUP_URL}", flush=True)
        resp = await page.goto(SIGNUP_URL, wait_until="domcontentloaded", timeout=30_000)
        print(f"[open] status={resp.status if resp else '?'} url={page.url}", flush=True)
        await page.wait_for_timeout(2000)
        info = await dump_page(page, "open")

        # Check for CAPTCHA
        cap = await page.evaluate("""() => ({
            recaptcha: !!document.querySelector('.g-recaptcha,[data-sitekey]'),
            hcaptcha:  !!document.querySelector('.h-captcha,[data-hcaptcha]'),
        })""")
        print(f"[captcha_check] {cap}", flush=True)
        if cap.get("recaptcha") or cap.get("hcaptcha"):
            write_status("captcha", "CAPTCHA detected — cannot proceed automatically")
            await browser.close()
            return

        # --- Step 2: fill login (email prefix) ---
        login_sel = None
        for sel in ['input[name="login"]', 'input[id="login"]', 'input[name="email"]',
                    'input[placeholder*="логін" i]', 'input[placeholder*="email" i]',
                    'input[type="text"]:first-of-type']:
            cnt = await page.locator(sel).count()
            if cnt > 0:
                login_sel = sel
                break

        if not login_sel:
            write_status("error", "Could not find login input")
            await dump_page(page, "no_login_input")
            await browser.close()
            return

        print(f"[fill_login] using selector: {login_sel}", flush=True)
        await page.click(login_sel)
        await js_fill(page, login_sel, login)
        await page.wait_for_timeout(500)

        # --- Step 3: fill password ---
        pass_sel = None
        for sel in ['input[name="password"]', 'input[type="password"]',
                    'input[id="password"]', 'input[name="pass"]']:
            cnt = await page.locator(sel).count()
            if cnt > 0:
                pass_sel = sel
                break

        if pass_sel:
            print(f"[fill_pass] using selector: {pass_sel}", flush=True)
            await page.click(pass_sel)
            await js_fill(page, pass_sel, password)
            await page.wait_for_timeout(300)

        # --- Step 4: fill password confirmation ---
        for sel in ['input[name="password_confirm"]', 'input[name="password2"]',
                    'input[name="confirm_password"]', 'input[id="password_confirm"]']:
            cnt = await page.locator(sel).count()
            if cnt > 0:
                print(f"[fill_pass2] using selector: {sel}", flush=True)
                await page.click(sel)
                await js_fill(page, sel, password)
                await page.wait_for_timeout(300)
                break

        # --- Step 5: fill name fields if present ---
        for name_map in [
            (['input[name="first_name"]', 'input[id="first_name"]',
              'input[placeholder*="ім\'я" i]', 'input[placeholder*="name" i]'], fname),
            (['input[name="last_name"]', 'input[id="last_name"]',
              'input[placeholder*="прізвищ" i]'], lname),
        ]:
            sels, val = name_map
            for sel in sels:
                cnt = await page.locator(sel).count()
                if cnt > 0:
                    print(f"[fill_name] {sel} = {val}", flush=True)
                    await page.click(sel)
                    await js_fill(page, sel, val)
                    await page.wait_for_timeout(300)
                    break

        await dump_page(page, "before_submit")

        # --- Step 6: submit ---
        submit_clicked = False
        for sel in ['button[type="submit"]', 'input[type="submit"]',
                    'button:has-text("Зареєструватися")', 'button:has-text("Реєстрація")',
                    'button:has-text("Створити")', 'button:has-text("Register")',
                    'button:has-text("Sign up")']:
            loc = page.locator(sel).first
            if await loc.count() > 0:
                print(f"[submit] clicking: {sel}", flush=True)
                await loc.click(timeout=5000)
                submit_clicked = True
                break

        if not submit_clicked:
            # JS fallback
            txt = await page.evaluate("""() => {
                const btn = [...document.querySelectorAll('button,input[type=submit]')]
                    .find(b => b.offsetParent !== null);
                if (btn) { btn.click(); return btn.textContent.trim().slice(0, 60); }
                return 'no_btn';
            }""")
            print(f"[submit] JS fallback clicked: {txt}", flush=True)

        await page.wait_for_timeout(3000)
        await dump_page(page, "after_submit")

        # --- Check result ---
        url = page.url
        body = await page.evaluate("() => document.body.innerText.slice(0, 500)")

        if "error" in url.lower() or "помилка" in body.lower() or "error" in body.lower():
            write_status("error", f"Registration failed. URL={url} body={body[:200]}")
        elif login in url or "success" in url.lower() or "вітаємо" in body.lower() \
                or "успішно" in body.lower() or "inbox" in url.lower() \
                or "mail" in url.lower():
            write_status("done", f"Registration successful! email={login}@ukr.net")
            # Save credentials
            creds = {"email": f"{login}@ukr.net", "password": password}
            Path("/home/bot/my-bot/ukrnet_creds.json").write_text(
                json.dumps(creds, indent=2))
            print(f"[done] ✅ {login}@ukr.net registered!", flush=True)
        else:
            write_status("unknown", f"Unclear result. URL={url} body={body[:200]}")
            print(f"[result] url={url}", flush=True)
            print(f"[result] body={body[:400]}", flush=True)

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
