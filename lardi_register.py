#!/usr/bin/env python3
"""
Lardi-Trans registration automation via Playwright.
Registers as Підприємець / Вантажовідправник with test data.
"""
import asyncio, json, os, time
from pathlib import Path
from playwright.async_api import async_playwright

STATUS_FILE = Path("/home/bot/my-bot/lardi_status.json")

CFG = {
    "first_name":  "Олег",
    "last_name":   "Коваленко",
    "patronymic":  "Іванович",
    "company_code": "1234567897",  # valid ІПН checksum: sum mod11 mod10 = 7
    "phone":       "+380969824425",
    "email":       "logisticAssistance@ukr.net",
    "login":       "logasst77143",
    "password":    "LogBot2026!",
}

REG_URL = "https://lardi-trans.com/uk/accounts/entrepreneur/?backurl=https://lardi-trans.com/log/dashboard/&referrer=https://lardi-trans.com"


def status(s, msg=""):
    STATUS_FILE.write_text(json.dumps({"status": s, "message": msg,
                                        "ts": time.strftime("%Y-%m-%d %H:%M:%S")}, indent=2))
    print(f"[{s}] {msg}", flush=True)


async def fill_input_nth(page, n, value):
    loc = page.locator('input[placeholder="Введіть"]').nth(n)
    await loc.click(timeout=5000)
    await loc.fill(value)
    await page.wait_for_timeout(200)


async def main():
    status("starting")
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled"],
        )
        ctx = await browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="uk-UA",
        )
        page = await ctx.new_page()

        # --- Load registration page ---
        print("[open] navigating to registration...", flush=True)
        await page.goto(REG_URL, wait_until="networkidle", timeout=30_000)
        await page.wait_for_timeout(2000)
        print(f"[open] url={page.url}", flush=True)

        # Check for CAPTCHA
        has_cap = await page.evaluate(
            "() => !!document.querySelector('.g-recaptcha,[data-sitekey],.h-captcha')"
        )
        if has_cap:
            status("captcha", "CAPTCHA detected")
            await browser.close()
            return

        # === STEP 1: Country / City ===
        # Page shows country selector (defaults to Netherlands) + city
        # Try to select Ukraine via react-select control
        page_text = await page.evaluate("() => document.body.innerText.slice(0, 200)")
        print(f"[step1] text={page_text[:100]}", flush=True)

        # Find react-select container by looking for the parent of the dummy input
        ukraine_selected = False
        try:
            # Click the container wrapping react-select-2-input
            await page.evaluate("""() => {
                const inp = document.getElementById('react-select-2-input');
                if (inp) {
                    // Walk up to the control container and click
                    let el = inp.parentElement;
                    while (el && !el.className.toString().includes('container')) el = el.parentElement;
                    if (el) el.click();
                }
            }""")
            await page.wait_for_timeout(500)
            await page.keyboard.type("Укра", delay=60)
            await page.wait_for_timeout(800)
            opt = page.locator('[class*="option"]:has-text("Україна"), [class*="option"]:has-text("Ukraine")').first
            if await opt.count() > 0:
                await opt.click(timeout=3000)
                ukraine_selected = True
                print("[step1] Ukraine selected", flush=True)
                await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[step1] country select error: {e}", flush=True)

        # City: Київ
        try:
            await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input[id^="react-select"]');
                const inp = inputs[1];
                if (inp) {
                    let el = inp.parentElement;
                    while (el && !el.className.toString().includes('container')) el = el.parentElement;
                    if (el) el.click();
                }
            }""")
            await page.wait_for_timeout(500)
            await page.keyboard.type("Київ", delay=60)
            await page.wait_for_timeout(800)
            opt2 = page.locator('[class*="option"]:has-text("Київ")').first
            if await opt2.count() > 0:
                await opt2.click(timeout=3000)
                print("[step1] Kyiv selected", flush=True)
                await page.wait_for_timeout(500)
        except Exception as e:
            print(f"[step1] city select error: {e}", flush=True)

        # Click Далі
        await page.locator('button:has-text("Далі")').click(timeout=5000)
        await page.wait_for_timeout(1500)
        print(f"[step1] after Далі, url={page.url}", flush=True)

        # === STEP 2: Who are you? ===
        page_text2 = await page.evaluate("() => document.body.innerText.slice(0, 300)")
        print(f"[step2] text={page_text2[:150]}", flush=True)

        # Select type: Підприємець
        for txt in ["Підприємець", "Фізична особа"]:
            loc = page.locator(f'text="{txt}"').first
            if await loc.count() > 0:
                await loc.click(timeout=3000)
                print(f"[step2] type clicked: {txt}", flush=True)
                await page.wait_for_timeout(400)
                break

        # Select role: Вантажовідправник
        for txt in ["Вантажовідправник", "Перевізник"]:
            loc = page.locator(f'text="{txt}"').first
            if await loc.count() > 0:
                await loc.click(timeout=3000)
                print(f"[step2] role clicked: {txt}", flush=True)
                await page.wait_for_timeout(400)
                break

        # Click Далі
        await page.locator('button:has-text("Далі")').click(timeout=5000)
        await page.wait_for_timeout(1500)
        print(f"[step2] after Далі, url={page.url}", flush=True)

        # === STEP 3: Fill registration form ===
        page_text3 = await page.evaluate("() => document.body.innerText.slice(0, 400)")
        print(f"[step3] text={page_text3[:200]}", flush=True)

        # Count available inputs
        inp_count = await page.locator('input[placeholder="Введіть"]').count()
        print(f"[step3] inputs with placeholder=Введіть: {inp_count}", flush=True)

        # Fields order based on page: Ім'я, Прізвище, По батькові, Код компанії, Телефон, Email, Логін, Пароль
        # Indices 0..7 (skipping react-select hidden inputs)
        fields = [
            (0, CFG["first_name"]),
            (1, CFG["last_name"]),
            (2, CFG["patronymic"]),
            (3, CFG["company_code"]),
            (4, CFG["phone"]),
            (5, CFG["email"]),
            (6, CFG["login"]),
        ]
        for idx, val in fields:
            try:
                await fill_input_nth(page, idx, val)
                print(f"[step3] filled input[{idx}]={val!r}", flush=True)
            except Exception as e:
                print(f"[step3] input[{idx}] error: {e}", flush=True)

        # "Звідки дізналися про нас?" — react-select-5, click and pick first option
        try:
            await page.evaluate("""() => {
                const inputs = document.querySelectorAll('input[id^="react-select"]');
                const inp = inputs[inputs.length - 1];
                if (inp) {
                    let el = inp.parentElement;
                    while (el && !el.className.toString().includes('container')) el = el.parentElement;
                    if (el) el.click();
                }
            }""")
            await page.wait_for_timeout(600)
            opt_ref = page.locator('[class*="option"]').first
            if await opt_ref.count() > 0:
                txt_ref = await opt_ref.text_content()
                print(f"[step3] referral option: {txt_ref}", flush=True)
                await opt_ref.click(timeout=3000)
                await page.wait_for_timeout(300)
        except Exception as e:
            print(f"[step3] referral error: {e}", flush=True)

        # Password field (type=password)
        try:
            pwd_loc = page.locator('input[type="password"]').first
            await pwd_loc.click(timeout=3000)
            await pwd_loc.fill(CFG["password"])
            print(f"[step3] filled password", flush=True)
        except Exception as e:
            print(f"[step3] password error: {e}", flush=True)

        # Checkbox: agree to terms
        try:
            cb = page.locator('input[type="checkbox"]').first
            if await cb.count() > 0 and not await cb.is_checked():
                await cb.check()
                print("[step3] checkbox checked", flush=True)
        except Exception as e:
            print(f"[step3] checkbox error: {e}", flush=True)

        # Screenshot state before submit
        inputs_state = await page.evaluate(
            "() => [...document.querySelectorAll('input:not([type=hidden])')].map(e => ({type:e.type,val:e.value.slice(0,30),checked:e.checked}))"
        )
        print(f"[step3] form state: {json.dumps(inputs_state, ensure_ascii=False)}", flush=True)

        # Click Зареєструватися
        submit = page.locator('button:has-text("Зареєструватися")')
        if await submit.count() > 0:
            print("[submit] clicking Зареєструватися...", flush=True)
            await submit.click(timeout=5000)
            await page.wait_for_timeout(3000)
        else:
            print("[submit] button not found!", flush=True)

        # === Check result ===
        url_after = page.url
        body_after = await page.evaluate("() => document.body.innerText.slice(0, 600)")
        print(f"[result] url={url_after}", flush=True)
        print(f"[result] body={body_after[:400]}", flush=True)

        # Check for success: URL should change away from /accounts/entrepreneur/
        registered = ("accounts/entrepreneur" not in url_after and
                      ("dashboard" in url_after or "cabinet" in url_after or "log" in url_after.split("?")[0]))
        if registered:
            status("done", f"Registered! Login: {CFG['login']}")
        elif "error" in body_after.lower() or "помилка" in body_after.lower():
            status("error", body_after[:200])
        elif "вже" in body_after.lower() or "already" in body_after.lower():
            status("exists", "Account already exists")
        else:
            status("unknown", f"url={url_after} body={body_after[:150]}")

        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
