#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打开视频号助手浏览器（不自动关闭），让老 K 手动操作验证。

用法：
  python scripts/manual_login.py

打开后老 K 可以：
- 看视频号内容管理 > 视频：14-15 章定时状态
- 看 14-15 章是否包含"不显示位置"
- 看老 01:00 草稿 → 手动删除
- 任何手动操作

按 Ctrl+C 退出。
"""
import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("错误：未安装 playwright")
    sys.exit(1)

USER_DATA_DIR = Path(__file__).parent.parent / "browser_data"


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            no_viewport=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.bring_to_front()

        print("=" * 50)
        print("视频号助手 - 手动验证模式")
        print("=" * 50)
        print()

        # 打开视频号内容管理
        print("正在打开视频号内容管理...")
        await page.goto(
            "https://channels.weixin.qq.com/platform/post/list",
            timeout=60000,
            wait_until="domcontentloaded",
        )
        await asyncio.sleep(3)
        print(f"当前 URL: {page.url}")
        print()

        # 如果是登录页（cookie 失效），提示扫码
        if "login" in page.url or "passport" in page.url:
            print("⚠️  Cookie 已失效，请在浏览器中扫码登录...")
            print()
            print("等待扫码（最多 10 分钟）...")
            for i in range(600):
                await asyncio.sleep(1)
                if "login" not in page.url and "passport" not in page.url:
                    print(f"✅ 登录成功！URL: {page.url}")
                    break
                if i % 10 == 0 and i > 0:
                    print(f"   等待扫码... ({i}s)")
            else:
                print("❌ 超时（10 分钟）")
                await ctx.close()
                return

        # 跳转到视频 tab 帮老 K 看
        print()
        print("正在切换到'视频' tab...")
        target = page
        for f in page.frames:
            if 'platform' in f.url or 'post/list' in f.url:
                target = f
                break
        try:
            # 找"视频" tab
            tab = target.locator('text=视频').first
            await tab.click(timeout=5000)
            await asyncio.sleep(2)
            print(f"当前 URL: {page.url}")
        except Exception as e:
            print(f"切换 tab 失败（手动点）: {e}")

        print()
        print("=" * 50)
        print("浏览器已就绪！")
        print()
        print("可以查看：")
        print("  • 14-15 章新草稿的定时时间（应该是 21:30）")
        print("  • 14-15 章新草稿的位置字段（应该是'不显示位置'）")
        print("  • 老 14-15 章 01:00 草稿（可手动删除）")
        print()
        print("按 Ctrl+C 退出")
        print("=" * 50)
        print()

        # 永远等（直到 Ctrl+C）
        try:
            await asyncio.sleep(3600 * 24)  # 24 小时
        except KeyboardInterrupt:
            print("\n收到 Ctrl+C，正在关闭...")
            await ctx.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n退出")