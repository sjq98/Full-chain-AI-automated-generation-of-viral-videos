#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信视频号登录 Cookie 获取脚本（v2 - persistent context）"""

import asyncio
import os
import sys
import json
from pathlib import Path

PUBLISHERS_DIR = Path(__file__).resolve().parents[2]
if str(PUBLISHERS_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHERS_DIR))

from chrome_runtime import (
    CHROME_LAUNCH_ARGS,
    PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
    keep_only_page_async,
    prepare_single_visible_page_async,
    restore_visible_window_async,
)

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("错误：未安装 playwright", flush=True)
    print("请运行：pip install playwright && playwright install chromium", flush=True)
    exit(1)

# 强制 unbuffered
sys.stdout.reconfigure(line_buffering=True)

COOKIE_DIR = Path(os.environ.get("WEIXIN_COOKIE_DIR") or (Path(__file__).parent.parent / "cookies"))
COOKIE_FILE = COOKIE_DIR / "weixin_video.json"
USER_DATA_DIR = Path(os.environ.get("WEIXIN_BROWSER_DATA_DIR") or (Path(__file__).parent.parent / "browser_data"))
BROWSER_EXECUTABLE = os.environ.get("PUBLISHER_BROWSER_EXECUTABLE") or os.environ.get("GOOGLE_CHROME_BIN")
CHANNELS_HOME_URL = "https://channels.weixin.qq.com/platform/post/list"

async def get_weixin_cookie():
    COOKIE_DIR.mkdir(parents=True, exist_ok=True)
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 50, flush=True)
    print("微信视频号登录 Cookie 获取 v2", flush=True)
    print("=" * 50, flush=True)
    print(flush=True)
    print("即将打开浏览器，请使用微信扫码登录", flush=True)
    print("登录成功后自动保存 cookie，无需其他操作", flush=True)
    print(flush=True)

    async with async_playwright() as p:
        if not BROWSER_EXECUTABLE or not Path(BROWSER_EXECUTABLE).is_file():
            raise RuntimeError("未找到 Google Chrome；视频号登录不会回退到 Edge 或 Playwright 浏览器")
        # Keep the upstream persistent-context flow: one headed Chrome window
        # and one initial page. Do not create a second CDP-owned browser.
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            executable_path=BROWSER_EXECUTABLE,
            headless=False,
            viewport=None,
            ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
            args=CHROME_LAUNCH_ARGS,
        )
        page = await prepare_single_visible_page_async(context, CHANNELS_HOME_URL)
        print(f"已直接打开 Google Chrome: {BROWSER_EXECUTABLE}", flush=True)

        # 访问视频号平台首页（列表页），未登录会弹二维码
        print("正在打开视频号平台...", flush=True)
        try:
            await page.goto(
                CHANNELS_HOME_URL,
                timeout=60000,
                wait_until="domcontentloaded",
            )
            await keep_only_page_async(context, page)
            await restore_visible_window_async(page)
        except Exception as e:
            print(f"页面加载提示: {e}", flush=True)

        await asyncio.sleep(2)
        print(f"当前 URL: {page.url}", flush=True)

        # 轮询检测登录：看页面上有没有"发表内容"按钮或用户头像
        print("请在浏览器中扫码登录...", flush=True)
        print("（登录成功后自动继续，无需点任何按钮）", flush=True)

        max_wait = 600
        logged_in = False
        for i in range(max_wait):
            await asyncio.sleep(1)
            try:
                if page.is_closed():
                    raise RuntimeError("PUBLISHER_USER_CLOSED_WINDOW 用户已关闭视频号登录窗口")
                url = page.url
                # 方法1: URL 不含 login/passport 且不是空白
                url_ok = "login" not in url and "passport" not in url and len(url) > 30

                # 方法2: 页面上有"发表内容"或"创建"按钮 = 登录成功
                elem_ok = False
                if url_ok:
                    try:
                        # 视频号登录后有"发表内容"按钮
                        btn = page.locator('text=发表内容')
                        if await btn.count() > 0:
                            elem_ok = True
                        # 或者有创建按钮
                        if not elem_ok:
                            btn = page.locator('text=创建')
                            if await btn.count() > 0:
                                elem_ok = True
                        # 或者 URL 包含 /platform/ 且不在登录页
                        if not elem_ok and "/platform/" in url:
                            elem_ok = True
                    except Exception:
                        pass

                if url_ok and elem_ok:
                    # 再等 3 秒确保所有 cookie 都设好
                    await asyncio.sleep(3)
                    url2 = page.url
                    if "login" not in url2 and "passport" not in url2:
                        logged_in = True
                        print(f"✅ 检测到登录成功！URL: {url2}", flush=True)
                        break
            except RuntimeError as exc:
                if "PUBLISHER_USER_CLOSED_WINDOW" in str(exc):
                    raise
            except Exception:
                pass

            if i % 10 == 0 and i > 0:
                print(f"   等待扫码登录... ({i}s)", flush=True)

        if not logged_in:
            print("❌ 等待超时（10分钟），请重新运行", flush=True)
            await context.close()
            return

        # 等页面完全稳定，多存几次
        print("登录成功，等待页面稳定...", flush=True)
        await asyncio.sleep(3)

        # 先导航到一个简单页面确保所有 cookie 都设置
        try:
            await page.goto(CHANNELS_HOME_URL,
                            timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(2)
        except Exception:
            pass

        # 保存 storage_state（给 publish.py 用）
        await context.storage_state(path=str(COOKIE_FILE))

        # 验证 cookie
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        cookie_count = len(data.get("cookies", []))

        if cookie_count < 5:
            print(f"⚠️  cookie 只有 {cookie_count} 个，再等 5 秒重试...", flush=True)
            await asyncio.sleep(5)
            await context.storage_state(path=str(COOKIE_FILE))
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            cookie_count = len(data.get("cookies", []))

        print(flush=True)
        print("=" * 50, flush=True)
        print(f"✅ Cookie 已保存到: {COOKIE_FILE}", flush=True)
        print(f"   cookie 数量: {cookie_count}", flush=True)
        print(f"   localStorage: {len(data.get('origins', []))} 个", flush=True)
        print(f"   browser_data: {USER_DATA_DIR}", flush=True)
        print("=" * 50, flush=True)

        await context.close()


def main():
    asyncio.run(get_weixin_cookie())


if __name__ == "__main__":
    main()
