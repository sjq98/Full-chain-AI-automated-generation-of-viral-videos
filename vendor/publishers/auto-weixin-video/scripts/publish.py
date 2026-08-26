#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信视频号视频发布脚本（拷贝自 auto-weixin-video skill）"""

import argparse
import asyncio
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

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
    from playwright.async_api import async_playwright, Page
except ImportError:
    print("错误：未安装 playwright")
    print("请运行：pip install playwright && playwright install chromium")
    sys.exit(1)


COOKIE_DIR = Path(os.environ.get("WEIXIN_COOKIE_DIR") or (Path(__file__).parent.parent / "cookies"))
COOKIE_FILE = COOKIE_DIR / "weixin_video.json"
BROWSER_EXECUTABLE = os.environ.get("PUBLISHER_BROWSER_EXECUTABLE") or os.environ.get("GOOGLE_CHROME_BIN")
CHANNELS_PUBLISH_URL = "https://channels.weixin.qq.com/platform/post/create"


def publisher_logs_dir() -> Path:
    target = Path(os.environ.get("WEIXIN_LOG_DIR") or (Path(__file__).parent.parent / "logs"))
    target.mkdir(parents=True, exist_ok=True)
    return target


async def restore_saved_cookies(context):
    """Import cookies without the saved localStorage payload that crashes Chrome."""
    if not COOKIE_FILE.exists():
        return
    try:
        import json
        state = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        if cookies:
            await context.add_cookies(cookies)
    except Exception as exc:
        print(f"⚠️ 无法导入已保存的视频号 Cookie，请重新登录：{exc}")


class WeixinVideoUploader:
    def __init__(
        self,
        video_path: str,
        title: str,
        short_title: str = "",
        tags: List[str] = None,
        original: bool = False,
        category: str = None,
        schedule_time: datetime = None,
        is_draft: bool = False,
        headless: bool = False,
        cover_path: Optional[str] = None,
        mark_ai: bool = False,
        skip_publish: bool = False,
        keep_browser: int = 0,
        manual_finish: bool = False,
        no_location: bool = False,
    ):
        self.video_path = Path(video_path)
        self.title = title
        self.short_title = short_title.strip()
        self.tags = tags or []
        self.original = original
        self.category = category
        self.schedule_time = schedule_time
        self.is_draft = is_draft
        self.headless = headless
        self.cover_path = Path(cover_path) if cover_path else None
        self.mark_ai = mark_ai
        self.skip_publish = skip_publish
        self.keep_browser = keep_browser
        self.manual_finish = manual_finish  # 半自动模式：跑完自动部分后老K手动勾原创/AI/发表
        self.no_location = no_location  # 不显示位置（清空'广州市'等默认位置）
        self.direct_chrome = False

        if not self.video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {self.video_path}")
        if self.cover_path and not self.cover_path.exists():
            raise FileNotFoundError(f"封面文件不存在: {self.cover_path}")

    async def upload(self) -> bool:
        print("=" * 60)
        print("微信视频号发布")
        print("=" * 60)
        print(f"视频: {self.video_path}")
        print(f"视频描述: {self.title}")
        print(f"短标题: {self.short_title or '自动从视频描述生成'}")
        print(f"话题: {', '.join(self.tags) if self.tags else '无'}")
        print(f"原创: {'是' if self.original else '否'}")
        print(f"封面: {self.cover_path if self.cover_path else '自动截取'}")
        print(f"AI标注: {'是' if self.mark_ai else '否'}")
        print(f"定时: {self.schedule_time.strftime('%Y-%m-%d %H:%M') if self.schedule_time else '立即发布'}")
        print(f"模式: {'草稿' if self.is_draft else ('跳过发布' if self.skip_publish else '正式发布')}")
        print()

        if not COOKIE_FILE.exists():
            print("❌ Cookie 文件不存在，请先运行 get_cookie.py")
            return False

        async with async_playwright() as p:
            self.direct_chrome = False
            if not BROWSER_EXECUTABLE or not Path(BROWSER_EXECUTABLE).is_file():
                raise RuntimeError("未找到 Google Chrome；视频号发布不会回退到 Edge 或 Playwright 浏览器")
            browser = await p.chromium.launch(
                headless=False,
                executable_path=BROWSER_EXECUTABLE,
                ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
                args=CHROME_LAUNCH_ARGS,
            )
            context = await browser.new_context(viewport=None)
            await restore_saved_cookies(context)
            print(f"已直接打开 Google Chrome: {BROWSER_EXECUTABLE}")
            try:
                page = await prepare_single_visible_page_async(context, CHANNELS_PUBLISH_URL)

                print("[1/7] 打开视频号创作者中心...")
                await page.goto(
                    CHANNELS_PUBLISH_URL,
                    timeout=60000,
                    wait_until="domcontentloaded",
                )
                await keep_only_page_async(context, page)
                await restore_visible_window_async(page)
                # 等 2 秒让页面做可能的客户端跳转
                await asyncio.sleep(2)
                # 检查是否被重定向到登录页
                if "login" in page.url or "passport" in page.url:
                    print("❌ Cookie 已过期，被重定向到登录页！")
                    print(f"   当前 URL: {page.url}")
                    print("   请重新运行 get_cookie.py 获取 cookie")
                    logs_dir = publisher_logs_dir()
                    await page.screenshot(path=str(logs_dir / "login-redirect.png"))
                    return False
                # 等 iframe 出现（视频号发布页是 iframe 嵌入）
                iframe = None
                for _ in range(30):
                    for f in page.frames:
                        if "micro/content/post/create" in f.url:
                            iframe = f
                            break
                    if iframe:
                        break
                    await asyncio.sleep(1)
                if not iframe:
                    print("   ⚠️  未找到发布 iframe，尝试在主页面操作")
                else:
                    # 等 iframe 内容加载完
                    try:
                        await iframe.wait_for_load_state("domcontentloaded", timeout=15000)
                    except Exception:
                        pass
                print(f"   页面已加载（iframe: {'✅' if iframe else '❌'}）, URL: {page.url}")

                print("[2/7] 上传视频文件...")
                # file input 可能在主页面或 iframe 里，两边都试
                uploaded = False
                for retry in range(3):
                    try:
                        # 先试 iframe（如果有），再试主页面
                        search_targets = []
                        if iframe:
                            search_targets.append(("iframe", iframe))
                        search_targets.append(("page", page))

                        for label, tgt in search_targets:
                            try:
                                file_input = tgt.locator('input[type="file"]')
                                if await file_input.count() > 0:
                                    await file_input.first.set_input_files(str(self.video_path), timeout=30000)
                                    uploaded = True
                                    print(f"   ✅ 视频上传成功（在 {label} 中找到 file input）")
                                    break
                            except Exception:
                                continue

                        if not uploaded:
                            raise Exception("所有位置都未找到 file input")
                        break
                    except Exception as e:
                        print(f"   视频上传 retry {retry+1}/3: {e}")
                        if retry < 2:
                            await asyncio.sleep(3)
                            # 重新找 iframe
                            for f in page.frames:
                                if "micro/content/post/create" in f.url:
                                    iframe = f
                                    break
                        else:
                            raise

                print("[3/7] 填写标题和话题...")
                await self._fill_title_and_tags(page)

                print("[4/7] 检查合集...")
                await self._add_to_collection(page)

                if self.manual_finish:
                    print("=" * 60)
                    print("⏸️  半自动模式：跑完自动部分")
                    print("=" * 60)
                    print("已自动完成：")
                    print("  ✅ 视频上传")
                    print("  ✅ 标题+话题")
                    print("  ✅ 合集检查")
                    print()
                    print("请手动完成以下步骤：")
                    print("  1️⃣  等待视频上传完成（看下方的进度条消失）")
                    print("  2️⃣  封面预览 → 编辑 → 上传封面 cover-05.jpg（如果没自动上）")
                    print("  3️⃣  勾选'声明原创' → 弹窗选原创类型 → 点确认")
                    print("  4️⃣  展开'视频标注' → 勾选'含 AI 生成内容'")
                    print("  5️⃣  短标题（已自动填）")
                    print("  6️⃣  点'发表'")
                    print("=" * 60)
                    # 跳到发布前的状态：等视频上传完 + 自动填短标题 + 自动选定时 + 自动上传封面
                    await self._wait_for_upload_complete(page)
                    if self.schedule_time:
                        await self._set_schedule_time(page)
                    await self._add_short_title(page)
                    await self._upload_cover(page)
                    # 截个图让老K看现状
                    logs_dir = publisher_logs_dir()
                    shot = logs_dir / f"manual-finish-{datetime.now():%Y%m%d%H%M%S}.png"
                    await page.screenshot(path=str(shot), full_page=True)
                    print(f"\n📸 当前状态截图：{shot.name}")
                    print(f"⏸️  浏览器保留 {self.keep_browser} 秒，老K手动操作...")
                    # 先存 cookie（浏览器关了就存不了）
                    await context.storage_state(path=str(COOKIE_FILE))
                    await self._maybe_keep_browser(browser, page)
                    return True

                print("[5/7] 声明原创...")
                await self._declare_original(page)

                print("[6/9] 标注含 AI 内容...")
                await self._mark_ai_content(page)

                print("[7/9] 等待视频上传完成...")
                await self._wait_for_upload_complete(page)

                if self.no_location:
                    print("[7.5/9] 清空位置字段...")
                    await self._clear_location(page)

                print("[8/9] 上传自定义封面...")
                await self._upload_cover(page)

                print("[9/9] 发布...")
                if self.schedule_time:
                    await self._set_schedule_time(page)

                await self._add_short_title(page)
                await self._publish(page)

                await context.storage_state(path=str(COOKIE_FILE))

                print()
                print("=" * 60)
                print("✅ 视频发布成功！")
                print("=" * 60)

                await self._maybe_keep_browser(browser, page)
                return True

            except Exception as e:
                detail = str(e)
                if e.__class__.__name__ == "TargetClosedError" or "Target page, context or browser has been closed" in detail:
                    print(f"PUBLISHER_USER_CLOSED_WINDOW 用户已关闭视频号发布窗口，任务已停止，未发布。", flush=True)
                print(f"❌ 发布失败: {e}")
                import traceback
                traceback.print_exc()
                await self._maybe_keep_browser(browser, page)
                return False

    async def _maybe_keep_browser(self, browser, page=None):
        """跑完后保留浏览器，让老K 可手动操作"""
        if self.keep_browser <= 0 and not self.manual_finish:
            if not self.direct_chrome:
                await browser.close()
            return
        print()
        if self.manual_finish:
            # manual-finish 模式：检测老K点发表后页面跳转，或等固定时间
            timeout = self.keep_browser if self.keep_browser > 0 else 600
            print("=" * 60)
            print("⏸️  浏览器已保留，老K手动操作：")
            print("   1. 勾「声明原创」→ 弹窗里选类型 → 确认")
            print("   2. 展开「视频标注」→ 勾「含AI生成内容」")
            print("   3. 确认封面、定时发布时间")
            print("   4. 点「发表」")
            print("=" * 60)
            print(f"   最多等 {timeout} 秒，发表成功后自动继续下一个...")
            # 轮询检测：页面跳转到 post/list 说明发表成功
            deadline = asyncio.get_event_loop().time() + timeout
            published = False
            while asyncio.get_event_loop().time() < deadline:
                try:
                    if page and page.is_closed():
                        print("PUBLISHER_USER_CLOSED_WINDOW 用户已关闭视频号发布窗口，任务已停止，未发布。", flush=True)
                        return
                    if page and ("post/list" in page.url or "post/manage" in page.url):
                        published = True
                        break
                except Exception as exc:
                    detail = str(exc)
                    if exc.__class__.__name__ == "TargetClosedError" or "Target page, context or browser has been closed" in detail:
                        print("PUBLISHER_USER_CLOSED_WINDOW 用户已关闭视频号发布窗口，任务已停止，未发布。", flush=True)
                        return
                await asyncio.sleep(2)
            if published:
                print("✅ 检测到发表成功（页面已跳转），继续下一个...")
            else:
                print(f"⏰ 等待超时（{timeout}秒），继续下一个...")
        else:
            print(f"⏸️  保留浏览器 {self.keep_browser} 秒，老K 可以手动查看页面...")
            print(f"   按 Ctrl+C 立即关闭")
            try:
                await asyncio.sleep(self.keep_browser)
            except asyncio.CancelledError:
                pass
        if not self.direct_chrome:
            await browser.close()

    async def _fill_title_and_tags(self, page: Page):
        """关键修复：标题+话题一起填到 div.input-editor（视频号统一富文本编辑器）"""
        await page.locator("div.input-editor").first.click()
        await page.keyboard.type(self.title)
        await page.keyboard.press("Enter")

        for tag in self.tags:
            await page.keyboard.type("#" + tag)
            await page.keyboard.press("Space")
            await asyncio.sleep(0.3)

        if self.tags:
            print(f"   已添加 {len(self.tags)} 个话题")

    async def _add_to_collection(self, page: Page):
        try:
            collection_elements = page.get_by_text("添加到合集").locator("xpath=following-sibling::div").locator(
                '.option-list-wrap > div')
            if await collection_elements.count() > 1:
                await page.get_by_text("添加到合集").locator("xpath=following-sibling::div").click()
                await collection_elements.first.click()
                print("   已添加到合集")
        except Exception:
            print("   无可用合集")

    async def _declare_original(self, page: Page):
        """勾选声明原创 + 处理原创权益 modal。

        视频号用 Ant Design checkbox：每个 checkbox 是 <label class="ant-checkbox-wrapper">
        包含 <span class="ant-checkbox"> > <input class="ant-checkbox-input">。
        定位策略：找含"声明原创"文字的 label 父节点，再点它的 checkbox-input。
        """
        logs_dir = publisher_logs_dir()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")

        try:
            frame = None
            for f in page.frames:
                if "micro/content/post/create" in f.url:
                    frame = f
                    break
            target = frame if frame else page

            # 1) 探测当前"声明原创" checkbox 状态
            #    通过 class 中是否有 "ant-checkbox-checked" 判断
            state = await target.evaluate(
                """
                () => {
                    const labels = document.querySelectorAll('.label.with-tip-label, .label');
                    for (const lbl of labels) {
                        if ((lbl.innerText || '').trim() === '声明原创') {
                            const formItem = lbl.closest('.form-item');
                            if (formItem) {
                                const wrapper = formItem.querySelector('.ant-checkbox-wrapper');
                                const cb = formItem.querySelector('.ant-checkbox-input');
                                if (wrapper) {
                                    const checked = wrapper.className.includes('ant-checkbox-wrapper-checked')
                                        || (cb && cb.checked);
                                    return {found: true, checked: checked};
                                }
                            }
                        }
                    }
                    return {found: false};
                }
                """
            )
            print(f"   🔍 原创声明初始: {state}")

            # 2) 如果未勾选，点 checkbox
            if not state.get("checked"):
                clicked = await target.evaluate(
                    """
                    () => {
                        const labels = document.querySelectorAll('.label.with-tip-label, .label');
                        for (const lbl of labels) {
                            if ((lbl.innerText || '').trim() === '声明原创') {
                                const formItem = lbl.closest('.form-item');
                                if (formItem) {
                                    const cb = formItem.querySelector('.ant-checkbox-input');
                                    if (cb) {
                                        cb.click();
                                        return true;
                                    }
                                    // 兜底：直接点 .ant-checkbox-wrapper
                                    const wrapper = formItem.querySelector('.ant-checkbox-wrapper');
                                    if (wrapper) {
                                        wrapper.click();
                                        return true;
                                    }
                                }
                            }
                        }
                        return false;
                    }
                    """
                )
                if clicked:
                    print("   ✅ JS 已点 checkbox")
                else:
                    print("   ⚠️  JS 点击失败")

                # 用 Playwright 真点击 wrapper（React 受控组件对真实鼠标事件响应更好）
                try:
                    wrapper_loc = target.locator(
                        "xpath=//div[contains(@class,'form-item') and .//*[text()='声明原创']]//label[contains(@class,'ant-checkbox-wrapper')]"
                    ).first
                    if await wrapper_loc.count() > 0:
                        await wrapper_loc.scroll_into_view_if_needed(timeout=3000)
                        await wrapper_loc.click(force=True, timeout=3000)
                        print("   ✅ Playwright 真点击 wrapper")
                        await asyncio.sleep(1)
                except Exception as e:
                    print(f"   ℹ️  Playwright 兜底跳过: {e}")

                # 等弹窗动画显示
                await asyncio.sleep(4)
                # 3) 处理原创权益弹窗（用 page 查找，因为弹窗可能在主 frame）
            try:
                # 先在 page 上找弹窗
                dialog_in_page = page.locator('.weui-desktop-dialog:has-text("原创权益")').first
                dialog_in_frame = target.locator('.weui-desktop-dialog:has-text("原创权益")').first
                dialog = dialog_in_page if await dialog_in_page.count() > 0 else dialog_in_frame

                # 直接定位弹窗内 checkbox wrapper（Playwright 真点击）
                try:
                    agree_wrapper = dialog.locator('.ant-checkbox-wrapper').first
                    if await agree_wrapper.count() > 0:
                        await agree_wrapper.scroll_into_view_if_needed(timeout=3000)
                        await agree_wrapper.click(force=True, timeout=3000)
                        print("   ✅ 已勾选原创声明协议")
                        await asyncio.sleep(1.5)
                    else:
                        print("   ⚠️  未找到协议 checkbox")
                except Exception as e:
                    print(f"   ⚠️ 勾选协议失败: {e}")

                # 等按钮变可用，再点确认
                try:
                    confirm = dialog.locator(
                        '.weui-desktop-dialog__ft .weui-desktop-btn_primary:has-text("声明原创")'
                    ).first
                    # 等到按钮不是 disabled
                    for _ in range(20):
                        disabled = await confirm.evaluate(
                            "el => el.disabled || el.classList.contains('weui-desktop-btn_disabled') || el.getAttribute('disabled') !== null"
                        )
                        if not disabled:
                            break
                        await asyncio.sleep(0.5)
                    await confirm.click(timeout=5000)
                    print("   ✅ 已点击声明原创确认按钮")
                    await asyncio.sleep(2)
                except Exception as e:
                    print(f"   ⚠️ 确认按钮失败: {e}")

                # 等弹窗关闭
                try:
                    await dialog.wait_for(state="hidden", timeout=8000)
                except Exception:
                    pass

            except Exception as e:
                print(f"   ⚠️ 处理弹窗异常: {e}")

            # 4) 最终探测
            final = await target.evaluate(
                """
                () => {
                    const labels = document.querySelectorAll('.label.with-tip-label, .label');
                    for (const lbl of labels) {
                        if ((lbl.innerText || '').trim() === '声明原创') {
                            const formItem = lbl.closest('.form-item');
                            if (formItem) {
                                const cb = formItem.querySelector('.ant-checkbox-input');
                                if (cb) {
                                    return cb.checked || cb.getAttribute('aria-checked') === 'true';
                                }
                            }
                        }
                    }
                    return null;
                }
                """
            )
            print(f"   🔍 最终: {'✅原创声明已勾选' if final else '❌原创声明未勾选'}")
            if not final:
                await page.screenshot(
                    path=str(logs_dir / f"original-final-{stamp}.png"),
                    full_page=True,
                )

        except Exception as e:
            print(f"   ❌ 原创声明异常: {e}")
            try:
                await page.screenshot(
                    path=str(logs_dir / f"original-error-{stamp}.png"),
                    full_page=True,
                )
            except Exception:
                pass

    async def _upload_cover(self, page: Page):
        """上传自定义封面。每步真实探测 + 截图。"""
        if not self.cover_path:
            return False
        logs_dir = publisher_logs_dir()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")

        try:
            # 1) 点"封面预览"右侧"编辑"链接（force click 避免被遮挡）
            edit_selectors = [
                'div[class*="cover"] >> text=编辑',
                'span:has-text("编辑"):near(:text("封面预览"))',
                'a:has-text("编辑")',
                'button:has-text("编辑封面")',
                'text=设置封面', 'text=编辑封面', 'text=更换封面',
            ]
            clicked = False
            for sel in edit_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0:
                        # 用 force click 避免被其他元素遮挡
                        await btn.click(force=True, timeout=3000)
                        clicked = True
                        print(f"   已点封面编辑按钮（{sel}）")
                        break
                except Exception as e:
                    continue
            if not clicked:
                print("   ❌ 未找到'编辑'按钮")
                await page.screenshot(path=str(logs_dir / f"cover-noedit-{stamp}.png"), full_page=True)
                return False

            await asyncio.sleep(2)

            # 2) modal 出来后，可能要先点"上传封面"/"本地上传"按钮激活 file input
            upload_triggers = [
                'text=上传封面', 'text=本地上传', 'text=上传图片',
                'button:has-text("上传")', 'a:has-text("上传")',
            ]
            for sel in upload_triggers:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(force=True, timeout=2000)
                        print(f"   已点上传触发按钮（{sel}）")
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            # 3) 找 file input 上传
            input_selectors = [
                'input[type="file"][accept*="image"]',
                'input[type="file"][accept*="jpg"]',
                'input[type="file"][accept*="png"]',
                'input[type="file"][accept="image/*"]',
                'input[type="file"][accept*="jpeg"]',
            ]
            uploaded = False
            for sel in input_selectors:
                try:
                    inp = page.locator(sel).first
                    if await inp.count() == 0:
                        continue
                    await inp.set_input_files(str(self.cover_path))
                    uploaded = True
                    print(f"   ✅ 封面上传 set_input_files 成功（{sel}）")
                    break
                except Exception as e:
                    print(f"   封面 input {sel} 失败：{e}")
                    continue

            if not uploaded:
                print("   ❌ 封面上传失败：所有 file input 都不可用")
                await page.screenshot(path=str(logs_dir / f"cover-nofileinput-{stamp}.png"), full_page=True)
                return False

            # 4) 等视频号处理图片 + 真实探测
            await asyncio.sleep(3)

            # 探测：封面预览区域的 img 元素 src 是不是变成新图片（不是视频截帧）
            cover_state = await page.evaluate("""
                () => {
                    // 找"封面预览"附近所有 img
                    const labels = Array.from(document.querySelectorAll('*'));
                    let coverArea = null;
                    for (const el of labels) {
                        if (el.children.length === 0 && (el.innerText || '').trim() === '封面预览') {
                            coverArea = el.parentElement;
                            break;
                        }
                    }
                    const imgs = coverArea ? coverArea.querySelectorAll('img') : document.querySelectorAll('img[class*="cover"], img[class*="poster"]');
                    const result = [];
                    for (const img of imgs) {
                        result.push({
                            src: img.src ? img.src.slice(-60) : '',
                            w: img.naturalWidth || img.width,
                            h: img.naturalHeight || img.height,
                        });
                    }
                    return result;
                }
            """)
            print(f"   🔍 封面预览 img 探测: {cover_state}")

            # 截图让老K看效果
            await page.screenshot(path=str(logs_dir / f"cover-after-{stamp}.png"), full_page=True)
            print(f"   📸 截图保存: cover-after-{stamp}.png")

            # 关闭封面编辑 modal（如果有）
            close_selectors = [
                'button:has-text("完成")',
                'button:has-text("确定")',
                'button:has-text("确认")',
                'button:has-text("保存")',
                '.weui-desktop-dialog__close-btn',
                '[aria-label="关闭"]',
            ]
            for sel in close_selectors:
                try:
                    btn = page.locator(sel).first
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click(force=True, timeout=2000)
                        await asyncio.sleep(0.5)
                        break
                except Exception:
                    continue

            # 判断是否真的换封面了：9:16 比例的图（width/height ≈ 0.5625）
            ok = any(
                img.get('w') and img.get('h') and 0.5 < img['w'] / img['h'] < 0.6
                for img in cover_state
            )
            if ok:
                print(f"   ✅ 封面比例 9:16 确认（{self.cover_path.name} 已生效）")
                return True
            else:
                print(f"   ⚠️  封面比例异常，可能仍是视频截帧（看 cover-after-{stamp}.png 确认）")
                return False

        except Exception as e:
            print(f"   ❌ 封面上传异常：{e}")
            try:
                await page.screenshot(path=str(logs_dir / f"cover-error-{stamp}.png"), full_page=True)
            except Exception:
                pass
            return False

    async def _mark_ai_content(self, page: Page):
        """勾选"含 AI 生成内容"视频标注。

        视频号的"视频标注"区域默认是折叠的，需要先点开折叠区。
        AI标注 div 用 div 模拟 checkbox，必须用 JS click + mouse 事件序列才能触发状态变化。
        勾选成功后 className 包含 is-selected。
        """
        logs_dir = publisher_logs_dir()
        stamp = datetime.now().strftime("%Y%m%d%H%M%S")

        try:
            # 定位目标 frame
            frame = None
            for f in page.frames:
                if "micro/content/post/create" in f.url:
                    frame = f
                    break
            if not frame:
                print("   ❌ 未找到视频号发布 iframe，AI 标注跳过")
                return False

            target = frame

            # 1) 探测当前是否已勾选（含 AI 生成内容）
            initial_state = await target.evaluate(
                """
                () => {
                    const opts = document.querySelectorAll('.mark-tag-option, .option-main');
                    for (const el of opts) {
                        const txt = (el.innerText || '').trim();
                        if (txt.includes('含AI') || txt.includes('含 AI 生成') || txt === '含AI生成内容') {
                            const cls = (el.className || '').toString();
                            const ariaChecked = el.getAttribute('aria-checked');
                            const hasCheckedClass = cls.includes('checked');
                            return {
                                found: true,
                                text: txt,
                                cls: cls,
                                hasChecked: hasCheckedClass || ariaChecked === 'true',
                            };
                        }
                    }
                    return {found: false};
                }
                """
            )

            if initial_state.get("found") and initial_state.get("hasChecked"):
                print(f"   ✅ AI 标注已勾选（{initial_state.get('text', '')}）")
                return True

            # 2) 展开"视频标注"折叠区（如果还没展开）
            try:
                expand_candidates = [
                    'label:has-text("视频标注")',
                    'span:has-text("视频标注")',
                    'div:has-text("视频标注")',
                    '[class*="mark-tag"]:has-text("视频标注")',
                    '[class*="video-mark"]',
                ]
                for sel in expand_candidates:
                    loc = target.locator(sel).first
                    if await loc.count() > 0:
                        try:
                            await loc.click(timeout=2000)
                            print(f"   已展开视频标注区域（{sel}）")
                            await asyncio.sleep(1.5)
                            break
                        except Exception:
                            continue
            except Exception:
                pass

            # 3) 找"含 AI 生成内容"选项并点选
            clicked = await target.evaluate(
                """
                () => {
                    // 候选 1：.mark-tag-option 包含"含AI"文字
                    const cands = document.querySelectorAll('.mark-tag-option, .option-main');
                    for (const el of cands) {
                        const txt = (el.innerText || '').trim();
                        if (txt.includes('含AI') || txt === '含AI生成内容' || txt === '含 AI 生成内容') {
                            el.scrollIntoView({block: 'center'});
                            el.click();
                            return {text: txt, cls: el.className};
                        }
                    }
                    // 候选 2：用文字匹配所有可见 div
                    const allDivs = document.querySelectorAll('div, label, span');
                    for (const el of allDivs) {
                        const txt = (el.innerText || '').trim();
                        if (txt === '含AI生成内容' || txt === '含 AI 生成内容') {
                            el.scrollIntoView({block: 'center'});
                            el.click();
                            return {text: txt, cls: el.className};
                        }
                    }
                    return null;
                }
                """
            )
            if clicked:
                print(f"   ✅ 已点击含 AI 生成内容选项（{clicked.get('text')}）")
            else:
                print("   ⚠️  未找到含 AI 生成内容选项")
            await asyncio.sleep(2)

            # 4) 兜底：用 React 合成事件强制勾选 + 多次重试
            final_state = {"found": False, "hasChecked": False, "text": ""}
            for attempt in range(3):
                final_state = await target.evaluate(
                    """
                    () => {
                        const opts = document.querySelectorAll('.mark-tag-option, .option-main');
                        for (const el of opts) {
                            const txt = (el.innerText || '').trim();
                            if (txt.includes('含AI') || txt === '含AI生成内容') {
                                const cls = (el.className || '').toString();
                                return {
                                    found: true,
                                    text: txt,
                                    hasChecked: cls.includes('checked') || cls.includes('active') || cls.includes('is-selected'),
                                    cls: cls,
                                };
                            }
                        }
                        return {found: false};
                    }
                    """
                )
                if final_state.get("hasChecked"):
                    break

                try:
                    await target.evaluate(
                        """
                        () => {
                            const opts = document.querySelectorAll('.mark-tag-option, .option-main');
                            for (const el of opts) {
                                const txt = (el.innerText || '').trim();
                                if (txt.includes('含AI') || txt === '含AI生成内容') {
                                    el.scrollIntoView({block: 'center'});
                                    const rect = el.getBoundingClientRect();
                                    const cx = rect.left + rect.width / 2;
                                    const cy = rect.top + rect.height / 2;
                                    ['mouseenter', 'mouseover', 'mousedown', 'focus', 'mouseup', 'click'].forEach(t => {
                                        el.dispatchEvent(new MouseEvent(t, {
                                            bubbles: true, cancelable: true,
                                            view: window, clientX: cx, clientY: cy, button: 0,
                                        }));
                                    });
                                    el.click();
                                    return true;
                                }
                            }
                            return false;
                        }
                        """
                    )
                    await asyncio.sleep(1.5)
                except Exception:
                    pass

            if final_state.get("found") and final_state.get("hasChecked"):
                print(f"   ✅ AI 标注已勾选（{final_state.get('text', '')}）")
                return True
            else:
                print(f"   ❌ AI 标注未勾上（state={final_state}）")
                await page.screenshot(
                    path=str(logs_dir / f"ai-notchecked-{stamp}.png"),
                    full_page=True,
                )
                return False
        except Exception as e:
            print(f"   ❌ AI 标注异常: {e}")
            try:
                await page.screenshot(
                    path=str(logs_dir / f"ai-error-{stamp}.png"),
                    full_page=True,
                )
            except Exception:
                pass
            return False

    async def _wait_for_upload_complete(self, page: Page):
        max_attempts = 120
        for i in range(max_attempts):
            try:
                publish_btn = page.get_by_role("button", name="发表")
                cnt = await publish_btn.count()
                if cnt == 0:
                    if i % 10 == 0:
                        print(f"   正在上传... ({i}s)")
                    await asyncio.sleep(1)
                    continue
                cls = await publish_btn.get_attribute('class')
                if cls and "weui-desktop-btn_disabled" not in cls:
                    print("   视频上传完成")
                    return
                if i % 10 == 0:
                    print(f"   正在上传... ({i}s)")
                await asyncio.sleep(1)
            except Exception:
                await asyncio.sleep(1)
        raise TimeoutError("视频上传超时")

    async def _set_schedule_time(self, page: Page):
        """设置定时发布时间。视频号默认是明天 21:00，必须改成 schedule_time 指定的日期+小时+分钟。

        关键发现（2026-07-31）：
        - 定时控件（"定时发布"radio、日期 picker、时间 input）**在 iframe 里**，必须用 target (frame)
        - 原代码用 page 找不到 picker，cnt=42 是 main frame 的无关链接
        - 必须：选月份 → 点日期 → 输入完整 HH:MM
        """
        if not self.schedule_time:
            return

        # 切到 iframe（定时控件在 micro/content/post/create 里）
        frame = None
        for f in page.frames:
            if "micro/content/post/create" in f.url:
                frame = f
                break
        target = frame if frame else page

        target_day = self.schedule_time.day
        target_hour = self.schedule_time.hour
        target_minute = self.schedule_time.minute
        target_month = self.schedule_time.month

        print(f"   定时目标: {self.schedule_time.strftime('%Y-%m-%d %H:%M')} (iframe: {'✅' if frame else '❌'})")

        try:
            # 1) 切到"定时" radio（视频号的 radio 文字是"定时"，不是"定时发布"）
            clicked_radio = False

            # 先 dump 一下 target 里 radio 实际数量
            radio_count = await target.locator('input[type="radio"]').count()
            print(f"   🔍 target 内 radio 总数: {radio_count}")

            # 方法 1：找精确 label "定时"（不是"不定时"），Playwright 真点击（React 会响应）
            try:
                # 用 xpath 找包含精确文字"定时"的 span（在 weui-desktop-form__check-content 里）
                spans = target.locator('span.weui-desktop-form__check-content')
                sp_cnt = await spans.count()
                print(f"   🔍 check-content span 数: {sp_cnt}")
                for i in range(sp_cnt):
                    s = spans.nth(i)
                    txt = (await s.inner_text()).strip()
                    if txt == '定时':
                        await s.click(force=True, timeout=3000)
                        clicked_radio = True
                        print(f"   ✅ 切到定时模式（Playwright 点 span='定时'）")
                        break
            except Exception as e:
                print(f"   span click 失败: {e}")

            # 方法 2：用 React 内部机制改 checked 属性 + 触发 change 事件
            if not clicked_radio:
                try:
                    result = await target.evaluate("""
                    () => {
                        const radios = document.querySelectorAll('input[type="radio"]');
                        for (const r of radios) {
                            if (r.value === '1') {
                                // 1) 设置 checked
                                const setter = Object.getOwnPropertyDescriptor(
                                    window.HTMLInputElement.prototype, 'checked'
                                ).set;
                                setter.call(r, true);
                                // 2) 触发 change 事件让 React 知道
                                r.dispatchEvent(new Event('click', {bubbles: true}));
                                r.dispatchEvent(new Event('change', {bubbles: true}));
                                return {clicked: true, now_checked: r.checked};
                            }
                        }
                        return {clicked: false};
                    }
                    """)
                    if result.get('clicked'):
                        clicked_radio = True
                        print(f"   ✅ 切到定时模式（React setter, now_checked={result.get('now_checked')}）")
                except Exception as e:
                    print(f"   React setter 失败: {e}")

            if not clicked_radio:
                print("   ⚠️  未找到定时 radio")
                return
            await asyncio.sleep(2.0)  # 等 React 重新渲染 date/time input

            # 验证：再次 dump radios 确认切换成功
            new_state = await target.evaluate("""
            () => {
                const radios = document.querySelectorAll('input[type="radio"]');
                const state = [];
                for (const r of radios) {
                    state.push({value: r.value, checked: r.checked});
                }
                return state;
            }
            """)
            import json as _json
            print(f"   🔍 切换后 radio 状态: {_json.dumps(new_state, ensure_ascii=False)}")

            # 2) 用 JS click 触发 picker（Playwright click 也会超时，但 JS click 能弹 picker）
            try:
                await target.evaluate("""
                () => {
                    const inp = document.querySelector('input[placeholder="请选择发表时间"]');
                    if (inp) {
                        inp.focus();
                        inp.click();
                    }
                }
                """)
                print("   ✅ 已触发日期 picker")
            except Exception as e:
                print(f"   ⚠️  触发 picker 失败: {e}")
                return
            await asyncio.sleep(1.5)

            # 3) 切换月份（如果日历当前显示的不是目标月）
            try:
                header_text = await target.evaluate("""
                () => {
                    const headers = document.querySelectorAll('.weui-desktop-picker__panel__hd');
                    for (const h of headers) {
                        const t = (h.innerText || '').trim();
                        if (t.includes('月')) return t;
                    }
                    return '';
                }
                """)
                import re as _re
                m = _re.search(r'(\d+)月', header_text)
                current_month = int(m.group(1)) if m else None
                print(f"   日历当前月份: {current_month} (header={header_text[:30]})")

                if current_month and current_month != target_month:
                    # 月份右箭头按钮：用 JS click（更稳定）
                    clicks_needed = (target_month - current_month) % 12
                    for click_i in range(clicks_needed):
                        try:
                            await target.evaluate(f"""
                            () => {{
                                const right = document.querySelector('.weui-desktop-picker__panel__hd .weui-desktop-btn__icon__right');
                                if (right) right.click();
                            }}
                            """)
                            await asyncio.sleep(0.6)
                        except Exception as e:
                            print(f"   月份 click {click_i+1} 失败: {e}")
                            break
                    # 验证
                    new_hd = await target.evaluate("""
                    () => {
                        const h = document.querySelector('.weui-desktop-picker__panel__hd');
                        return h ? h.innerText : '';
                    }
                    """)
                    print(f"   切换到目标月（{target_month}）后头部: {new_hd}")
            except Exception as e:
                print(f"   月份切换跳过: {e}")

            await asyncio.sleep(0.5)

            # 4) 直接用 JS 点目标日期（绕过 stale locator 问题）
            day_clicked = await target.evaluate(f"""
            () => {{
                const links = document.querySelectorAll('.weui-desktop-picker__table a');
                const targetDay = "{target_day}";
                for (const a of links) {{
                    const txt = a.innerText.trim();
                    const cls = a.className || '';
                    if (txt === targetDay && !cls.includes('disabled')) {{
                        a.click();
                        return {{clicked: true, text: txt}};
                    }}
                }}
                return {{clicked: false, total: links.length}};
            }}
            """)
            if day_clicked.get('clicked'):
                print(f"   ✅ 已选日期: {day_clicked.get('text')}")
            else:
                print(f"   ⚠️  未找到日期 {target_day}（{day_clicked}）")

            await asyncio.sleep(1)

            # 5) 用 Playwright 真点击 + 键盘输入（视频号时间 picker 是 React 18 自定义组件，
            #    dispatchEvent('input') 不会触发 onChange 同步，必须模拟真实键盘输入）
            time_str = f"{target_hour:02d}:{target_minute:02d}"
            try:
                # 5a) JS click 触发"请选择时间"聚焦（不是 readonly，普通 React 受控 input）
                clicked = await target.evaluate(f"""
                () => {{
                    const inp = document.querySelector('input[placeholder="请选择时间"]');
                    if (!inp) return {{found: false}};
                    inp.focus();
                    inp.click();
                    inp.select();
                    return {{found: true, val: inp.value, readonly: inp.readOnly}};
                }}
                """)
                if not clicked.get('found'):
                    print(f"   ⚠️  未找到时间 input（请选择时间）")
                else:
                    print(f"   🔍 时间 input: val={clicked.get('val')}, readonly={clicked.get('readonly')}")
                    await asyncio.sleep(0.5)

                    # 5b) 真实键盘输入（frame 没有 keyboard 属性，用 page.keyboard）
                    await page.keyboard.press('Control+A')
                    await page.keyboard.press('Delete')
                    await asyncio.sleep(0.2)
                    await page.keyboard.type(time_str, delay=120)
                    await asyncio.sleep(0.5)

                    # 5c) blur 触发 React 18 onChange 同步
                    await page.keyboard.press('Tab')
                    await asyncio.sleep(0.5)

                    # 5d) 验证
                    actual_time = await target.evaluate(f"""
                    () => {{
                        const inp = document.querySelector('input[placeholder="请选择时间"]');
                        return inp ? inp.value : '';
                    }}
                    """)
                    print(f"   ✅ 已填时间: {actual_time}（目标 {time_str}）")
            except Exception as e:
                print(f"   ⚠️  填时间失败: {e}")
                # fallback: 旧 JS 写法
                try:
                    time_result = await target.evaluate(f"""
                    () => {{
                        const inp = document.querySelector('input[placeholder="请选择时间"]');
                        if (!inp) return {{set: false, reason: 'not found'}};
                        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
                        setter.call(inp, '{time_str}');
                        inp.dispatchEvent(new Event('input', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('change', {{bubbles: true}}));
                        inp.dispatchEvent(new Event('blur', {{bubbles: true}}));
                        return {{set: true, newVal: inp.value}};
                    }}
                    """)
                    if time_result.get('set'):
                        print(f"   ⚠️  fallback 写入: {time_result.get('newVal')}（可能未生效）")
                except Exception as e2:
                    print(f"   ❌ fallback 也失败: {e2}")

            await asyncio.sleep(1)

            # 6) 验证最终定时
            actual = await target.evaluate("""
                () => {
                    const inputs = document.querySelectorAll('input[placeholder="请选择发表时间"]');
                    for (const inp of inputs) {
                        const v = inp.value;
                        if (v && v.includes('-')) return v;
                    }
                    return '';
                }
            """)
            print(f"   🔍 视频号显示的定时: {actual}")

        except Exception as e:
            print(f"   ❌ 定时设置失败: {e}")

    async def _clear_location(self, page: Page):
        """清空位置字段（视频号默认填'广州市'等创作者 profile 城市）。
        视频号位置字段结构：
        - .position-display-wrap 显示当前城市（默认'广州市'）
        - 点击后展开 .location-filter-wrap，含搜索框 + option 列表
        - option 列表第一项是"不显示位置"（class .option-item）
        策略：点击 .position-display-wrap → 找 .option-item 含"不显示位置" → 点击
        """
        try:
            frame = None
            for f in page.frames:
                if "micro/content/post/create" in f.url:
                    frame = f
                    break
            target = frame if frame else page

            # 1) 点击 .position-display-wrap 展开 dropdown
            clicked = await target.evaluate("""
            () => {
                const wrap = document.querySelector('.position-display-wrap');
                if (!wrap) return false;
                wrap.click();
                return true;
            }
            """)
            if not clicked:
                print("   ⚠️  未找到 .position-display-wrap（位置字段未显示）")
                return
            await asyncio.sleep(1.0)

            # 2) 找"不显示位置"选项并点击
            result = await target.evaluate("""
            () => {
                // dropdown 里的所有 .option-item
                const opts = document.querySelectorAll('.option-item');
                for (const opt of opts) {
                    const nameDiv = opt.querySelector('.name, .location-item-info');
                    const txt = nameDiv ? (nameDiv.innerText || '').trim() : (opt.innerText || '').trim();
                    if (txt === '不显示位置' || txt.includes('不显示')) {
                        opt.click();
                        return {clicked: true, text: txt};
                    }
                }
                return {clicked: false};
            }
            """)
            if result.get('clicked'):
                await asyncio.sleep(0.5)
                # 验证：位置应该清空（位置 display 不显示 city name）
                verify = await target.evaluate("""
                () => {
                    const nameSpan = document.querySelector('.location-name');
                    return {
                        visible: !!nameSpan && nameSpan.offsetParent !== null,
                        text: nameSpan ? (nameSpan.innerText || '').trim() : '',
                        displayShown: document.querySelector('.position-display') ? document.querySelector('.position-display').offsetParent !== null : false,
                    };
                }
                """)
                if not verify.get('visible') or not verify.get('text'):
                    print(f"   ✅ 位置已清空（display: {verify.get('displayShown')}）")
                else:
                    print(f"   ⚠️  点击后位置仍显示: '{verify.get('text')}'")
            else:
                print("   ⚠️  未找到'不显示位置'选项")
        except Exception as e:
            print(f"   ❌ 清空位置失败: {e}")

    async def _add_short_title(self, page: Page):
        try:
            short_title_element = page.get_by_text("短标题", exact=True).locator("..").locator(
                "xpath=following-sibling::div").locator('span input[type="text"]')
            if await short_title_element.count():
                short_title = (self.short_title or self.title[:14]).strip()
                if len(short_title) < 6:
                    short_title = ((self.short_title or self.title) + "    ")[:6]
                await short_title_element.fill(short_title)
                print(f"   已填短标题: {short_title}")
        except Exception:
            pass

    async def _publish(self, page: Page):
        if self.skip_publish:
            # 调试模式：不点发表按钮，截图 + 探测关键 checkbox 状态
            try:
                logs_dir = publisher_logs_dir()
                stamp = datetime.now().strftime("%Y%m%d%H%M%S")
                shot = logs_dir / f"skip-publish-{stamp}.png"
                await page.screenshot(path=str(shot), full_page=True)
                print(f"   截图保存: {shot}")
            except Exception as e:
                print(f"   截图失败: {e}")
            # 探测关键勾选状态（写到日志，不用打开浏览器也能确认）
            try:
                # 找视频号 iframe
                frame = None
                for f in page.frames:
                    if 'micro/content/post/create' in f.url:
                        frame = f
                        break
                target = frame if frame else page
                checks = await target.evaluate("""
                    () => {
                        const out = {};
                        // 原创声明
                        const origLabels = document.querySelectorAll('label, span, div');
                        for (const el of origLabels) {
                            const t = (el.innerText || '').trim();
                            if (t === '声明原创' || t === '原创') {
                                let cb = el.parentElement && el.parentElement.querySelector('input[type=checkbox]');
                                if (!cb) cb = el.closest('label') && el.closest('label').querySelector('input[type=checkbox]');
                                if (cb) out['原创声明'] = cb.checked;
                            }
                        }
                        // AI 标注（递归 Shadow DOM）
                        const walk = (root) => {
                            const candidates = root.querySelectorAll('.mark-tag-option');
                            for (const el of candidates) {
                                const txt = (el.innerText || '').trim();
                                if (txt.includes('含AI') || txt.includes('AI 生成')) {
                                    out['AI标注'] = !!el.querySelector('input[type=checkbox]:checked, .checked, [class*="checked"], [class*="is-selected"]') ||
                                                    el.className.includes('checked') ||
                                                    el.className.includes('is-selected') ||
                                                    el.className.includes('active') ||
                                                    el.getAttribute('aria-checked') === 'true';
                                    return;
                                }
                            }
                            const c2 = root.querySelectorAll('.option-main');
                            for (const el of c2) {
                                const txt = (el.innerText || '').trim();
                                if (txt === '含AI生成内容' || txt === '含 AI 生成内容') {
                                    out['AI标注'] = el.className.includes('checked') || el.className.includes('is-selected') || el.className.includes('active');
                                    return;
                                }
                            }
                            for (const el of root.querySelectorAll('*')) {
                                if (el.shadowRoot) walk(el.shadowRoot);
                            }
                        };
                        walk(document);
                        return out;
                    }
                """)
                print(f"   📋 勾选状态探测: {checks}")
            except Exception as e:
                print(f"   勾选探测失败：{e}")
            print("   ⏸️  跳过发布（保留页面，可去视频号草稿箱/创作页确认）")
            return

        for attempt in range(30):
            try:
                if self.is_draft:
                    draft_button = page.locator('div.form-btns button:has-text("保存草稿")')
                    if await draft_button.count():
                        await draft_button.first.click()
                    await page.wait_for_url("**/post/list**", timeout=5000)
                    return
                else:
                    publish_button = page.locator('div.form-btns button:has-text("发表")')
                    if await publish_button.count():
                        await publish_button.first.click()
                    await page.wait_for_url("https://channels.weixin.qq.com/platform/post/list", timeout=5000)
                    return
            except Exception:
                await asyncio.sleep(1)
        raise TimeoutError("发布超时")


def parse_args():
    parser = argparse.ArgumentParser(description="微信视频号自动发布")
    parser.add_argument("-v", "--video", required=True, help="视频文件路径")
    parser.add_argument("-t", "--title", required=True, help="视频描述")
    parser.add_argument("--short-title", default="", help="短标题（留空时从视频描述生成）")
    parser.add_argument("-g", "--tags", default="", help="话题标签，逗号分隔")
    parser.add_argument("-o", "--original", action="store_true", help="声明原创")
    parser.add_argument("-c", "--category", default=None, help="原创类型")
    parser.add_argument("-s", "--schedule", default=None, help="定时发布时间 YYYY-MM-DD HH:MM")
    parser.add_argument("--draft", action="store_true", help="保存为草稿")
    parser.add_argument("--headless", action="store_true", help="无头模式")
    parser.add_argument("--cover", default=None, help="封面图片路径（JPG/PNG）")
    parser.add_argument("--mark-ai", action="store_true", help="勾选'标注含 AI 生成内容'")
    parser.add_argument("--skip-publish", action="store_true", help="调试模式：跑完所有步骤但不点发表（截图保存）")
    parser.add_argument("--keep-browser", type=int, default=0, metavar="SEC", help="跑完后保留浏览器 N 秒（默认 0=立即关）")
    parser.add_argument("--manual-finish", action="store_true", help="半自动模式：跑完视频+封面+标题+短标题后保留浏览器，老K手动勾原创/AI/发表")
    parser.add_argument("--no-location", action="store_true", help="不显示位置（清空位置字段，避免默认显示'广州市'）")
    return parser.parse_args()


def main():
    args = parse_args()
    # 话题可能用逗号或空格分隔，且可能带 # 前缀
    raw_tags = args.tags.replace(",", " ").split() if args.tags else []
    tags = [t.lstrip("#").strip() for t in raw_tags if t.strip()]
    schedule_time = None
    if args.schedule:
        try:
            schedule_time = datetime.strptime(args.schedule, "%Y-%m-%d %H:%M")
        except ValueError:
            print("❌ 时间格式错误，应为 YYYY-MM-DD HH:MM")
            sys.exit(1)
    try:
        uploader = WeixinVideoUploader(
            video_path=args.video,
            title=args.title,
            short_title=args.short_title,
            tags=tags,
            original=args.original,
            category=args.category,
            schedule_time=schedule_time,
            is_draft=args.draft,
            headless=args.headless,
            cover_path=args.cover,
            mark_ai=args.mark_ai,
            skip_publish=args.skip_publish,
            keep_browser=args.keep_browser,
            manual_finish=args.manual_finish,
            no_location=args.no_location,
        )
        success = asyncio.run(uploader.upload())
        sys.exit(0 if success else 1)
    except FileNotFoundError as e:
        print(f"❌ {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
