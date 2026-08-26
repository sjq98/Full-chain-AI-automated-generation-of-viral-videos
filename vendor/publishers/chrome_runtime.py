"""Shared helpers for one visible, direct Google Chrome publisher window."""

from __future__ import annotations

from urllib.parse import urlsplit


CHROME_LAUNCH_ARGS = [
    "--window-position=60,40",
    "--window-size=1280,900",
    "--disable-blink-features=AutomationControlled",
]

# Playwright adds some compatibility switches to Chromium automatically. The
# installed Google Chrome should use the operating system's normal sandbox and
# GPU path, so filter those switches instead of compensating with more flags.
PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE = [
    "--no-sandbox",
    "--disable-gpu",
    "--disable-gpu-compositing",
    "--in-process-gpu",
    "--disable-software-rasterizer",
    "--enable-unsafe-swiftshader",
    "--use-gl=swiftshader",
    "--use-angle=swiftshader",
]


def _normalized_url(value):
    return str(value or "").strip().rstrip("/")


def _page_host(page):
    try:
        return urlsplit(str(page.url or "")).netloc.lower()
    except Exception:
        return ""


def _live_pages(context):
    pages = []
    for page in context.pages:
        try:
            if not page.is_closed():
                pages.append(page)
        except Exception:
            continue
    return pages


def reusable_page(context, target_url):
    """Select the current platform or blank page without opening another tab."""
    pages = _live_pages(context)
    normalized_target = _normalized_url(target_url)
    for page in pages:
        if _normalized_url(page.url) == normalized_target:
            return page
    target_host = urlsplit(str(target_url or "")).netloc.lower()
    if target_host:
        for page in pages:
            if _page_host(page) == target_host:
                return page
    for page in pages:
        if _normalized_url(page.url) in {"", "about:blank", "chrome://newtab"}:
            return page
    return None


def reuse_or_create_page(context, target_url):
    return reusable_page(context, target_url) or context.new_page()


async def reuse_or_create_page_async(context, target_url):
    return reusable_page(context, target_url) or await context.new_page()


def keep_only_page(context, keep_page):
    """Keep exactly one tab in a publisher-owned browser context."""
    closed = 0
    for page in _live_pages(context):
        if page is keep_page:
            continue
        try:
            page.close()
            closed += 1
        except Exception:
            pass
    return closed


async def keep_only_page_async(context, keep_page):
    closed = 0
    for page in _live_pages(context):
        if page is keep_page:
            continue
        try:
            await page.close()
            closed += 1
        except Exception:
            pass
    return closed


def restore_visible_window(page, left=60, top=40, width=1280, height=900):
    """Restore and position only the Chrome window that owns ``page``."""
    session = None
    try:
        page.bring_to_front()
        session = page.context.new_cdp_session(page)
        window_id = session.send("Browser.getWindowForTarget").get("windowId")
        if window_id is None:
            return False
        session.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": {"windowState": "normal"}},
        )
        session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {"left": left, "top": top, "width": width, "height": height},
            },
        )
        page.bring_to_front()
        return True
    except Exception:
        return False
    finally:
        if session is not None:
            try:
                session.detach()
            except Exception:
                pass


async def restore_visible_window_async(page, left=60, top=40, width=1280, height=900):
    session = None
    try:
        await page.bring_to_front()
        session = await page.context.new_cdp_session(page)
        window_id = (await session.send("Browser.getWindowForTarget")).get("windowId")
        if window_id is None:
            return False
        await session.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": {"windowState": "normal"}},
        )
        await session.send(
            "Browser.setWindowBounds",
            {
                "windowId": window_id,
                "bounds": {"left": left, "top": top, "width": width, "height": height},
            },
        )
        await page.bring_to_front()
        return True
    except Exception:
        return False
    finally:
        if session is not None:
            try:
                await session.detach()
            except Exception:
                pass


def prepare_single_visible_page(context, target_url):
    page = reuse_or_create_page(context, target_url)
    keep_only_page(context, page)
    restore_visible_window(page)
    return page


async def prepare_single_visible_page_async(context, target_url):
    page = await reuse_or_create_page_async(context, target_url)
    await keep_only_page_async(context, page)
    await restore_visible_window_async(page)
    return page
