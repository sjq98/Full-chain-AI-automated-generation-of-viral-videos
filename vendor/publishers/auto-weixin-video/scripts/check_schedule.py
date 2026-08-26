#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证视频号草稿/定时发布列表的实际定时时间"""
import asyncio
import sys
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("错误：未安装 playwright")
    sys.exit(1)

USER_DATA_DIR = Path(__file__).parent.parent / "browser_data"

CHAPTERS = ["14", "15"]  # 道德经 14-15 章


async def main():
    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            no_viewport=True,
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 视频号"内容管理"页面
        print("正在打开视频号内容管理...", flush=True)
        try:
            await page.goto(
                "https://channels.weixin.qq.com/platform/post/list",
                timeout=60000,
                wait_until="domcontentloaded",
            )
        except Exception as e:
            print(f"打开页面提示: {e}", flush=True)

        await asyncio.sleep(5)
        print(f"当前 URL: {page.url}", flush=True)

        # 找 video 号的 iframe
        target = page
        for f in page.frames:
            if 'post/list' in f.url or 'micro/content' in f.url:
                target = f
                break

        # 抓全部 tab 文字
        all_text = await target.evaluate("""
        () => {
            const tabs = document.querySelectorAll('[class*="tab"], [role="tab"], li, a, span');
            const out = [];
            for (const t of tabs) {
                const txt = (t.innerText || '').trim();
                if (txt && txt.length < 10) out.push(txt);
            }
            return out;
        }
        """)
        print(f"页面 tab/链接文字: {all_text}", flush=True)

        # 抓所有 14-15 章文字（包括其他状态）
        result = await target.evaluate("""
        () => {
            const out = [];
            const all = document.querySelectorAll('*');
            for (const el of all) {
                const text = (el.innerText || '').trim();
                if ((text.includes('第14章') || text.includes('第15章')) && text.length < 300) {
                    out.push({
                        text: text.substring(0, 200),
                        tag: el.tagName,
                        cls: el.className,
                    });
                }
            }
            return out;
        }
        """)
        print(f"\n==== 14-15 章状态 ====", flush=True)
        for r in result:
            print(f"[{r.get('tag')}] {r.get('text')}", flush=True)

        # 截图
        logs = Path(__file__).parent.parent / "logs"
        logs.mkdir(exist_ok=True)
        stamp = "verify-14-15"
        try:
            await page.screenshot(path=str(logs / f"{stamp}.png"), full_page=True)
            print(f"截图保存: {logs / f'{stamp}.png'}", flush=True)
        except Exception as e:
            print(f"截图失败: {e}", flush=True)

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
