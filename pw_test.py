"""
Playwright diagnostic: tests google.com AND accounts.google.com/signup.
Prints STATUS, URL, TITLE, page length, and whether firstName field exists.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright

SS_DIR = Path(__file__).parent / "screenshots"
SS_DIR.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--disable-blink-features=AutomationControlled"]
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

        # Patch webdriver flag
        await page.add_init_script(
            "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
        )

        # Test 1: google.com
        print("--- TEST 1: google.com ---", flush=True)
        try:
            r1 = await page.goto("https://www.google.com", wait_until="domcontentloaded", timeout=30_000)
            print(f"STATUS: {r1.status}", flush=True)
            print(f"URL: {page.url}", flush=True)
            print(f"TITLE: {await page.title()}", flush=True)
            await page.screenshot(path=str(SS_DIR / "test_google.png"))
            print("SCREENSHOT: test_google.png", flush=True)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)

        await asyncio.sleep(2)

        # Test 2: Gmail signup
        print("\n--- TEST 2: Gmail signup ---", flush=True)
        signup_url = (
            "https://accounts.google.com/signup/v2/webcreateaccount"
            "?flowName=GlifWebSignIn&flowEntry=SignUp"
        )
        try:
            r2 = await page.goto(signup_url, wait_until="commit", timeout=40_000)
            print(f"STATUS: {r2.status if r2 else 'n/a'}", flush=True)
            print(f"URL: {page.url}", flush=True)
            print(f"TITLE: {await page.title()}", flush=True)
            content = await page.content()
            print(f"PAGE_LENGTH: {len(content)}", flush=True)
            fn = page.locator('input[name="firstName"]')
            count = await fn.count()
            print(f"firstName_field_exists: {count > 0}", flush=True)
            await page.screenshot(path=str(SS_DIR / "test_signup.png"))
            print("SCREENSHOT: test_signup.png", flush=True)
        except Exception as e:
            print(f"ERROR: {e}", flush=True)
            try:
                await page.screenshot(path=str(SS_DIR / "test_signup_err.png"))
                print("SCREENSHOT: test_signup_err.png", flush=True)
            except Exception:
                pass

        await browser.close()
    print("\nPLAYWRIGHT_TEST_DONE", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
