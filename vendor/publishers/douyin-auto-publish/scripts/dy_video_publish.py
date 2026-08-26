"""
dy-video 抖音视频发布脚本
上传单个视频 → 填好表单 → 停留在发布页等待审核
"""
import os, sys, time, random, json, argparse, re
from pathlib import Path

PUBLISHERS_DIR = Path(__file__).resolve().parents[2]
if str(PUBLISHERS_DIR) not in sys.path:
    sys.path.insert(0, str(PUBLISHERS_DIR))

from chrome_runtime import (
    CHROME_LAUNCH_ARGS,
    PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
    keep_only_page,
    prepare_single_visible_page,
    restore_visible_window,
)
from playwright.sync_api import sync_playwright

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# === 日志 ===
LOG = os.environ.get("DOUYIN_LOG_FILE") or os.path.expanduser(r"~\.hermes\logs\dy_video.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

def log(msg):
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    print(msg, flush=True)

def human_wait(page, min_ms=300, max_ms=2000):
    delay = random.randint(min_ms, max_ms)
    _raise_if_publish_window_closed(page)
    try:
        page.wait_for_timeout(delay)
    except Exception as exc:
        _raise_if_publish_window_closed(page, exc)
        raise
    return delay

def human_type(page, text):
    total_delay = 0
    for char in text:
        delay = random.randint(50, 100)
        if random.random() < 0.05:
            delay += random.randint(200, 500)
        if char == '\n':
            delay += random.randint(300, 800)
        _raise_if_publish_window_closed(page)
        try:
            page.keyboard.type(char, delay=delay)
        except Exception as exc:
            _raise_if_publish_window_closed(page, exc)
            raise
        total_delay += delay
    return total_delay

# === 配置 ===
STATE_FILE = os.environ.get("DOUYIN_STATE_FILE") or os.path.expanduser(r"~\.hermes\browser-profiles\douyin_state.json")
BROWSER_EXECUTABLE = os.environ.get("PUBLISHER_BROWSER_EXECUTABLE") or os.environ.get("GOOGLE_CHROME_BIN")
LOCATION = ""

# The workbench supplies the metadata. Keep standalone defaults empty so no
# content from the original sample project appears in a user's draft.
DEFAULT_TITLE = ""
DEFAULT_BODY = ""
DEFAULT_TOPICS = []
PUBLISH_URL = "https://creator.douyin.com/creator-micro/content/upload"
USER_CLOSED_WINDOW_MARKER = "PUBLISHER_USER_CLOSED_WINDOW"
USER_CLOSED_WINDOW_MESSAGE = "用户已关闭抖音发布窗口，任务已停止，未发布。"


class UserClosedPublishWindow(RuntimeError):
    """Stop cleanly when the user closes the visible Chrome window."""


def _is_target_closed_error(error):
    return (
        error.__class__.__name__ == "TargetClosedError"
        or "Target page, context or browser has been closed" in str(error or "")
    )


def _raise_if_publish_window_closed(page, error=None):
    if error is not None and not _is_target_closed_error(error):
        return
    try:
        is_closed = page.is_closed()
    except Exception:
        is_closed = True
    if error is not None or is_closed:
        raise UserClosedPublishWindow(USER_CLOSED_WINDOW_MESSAGE) from None


def normalize_location(value):
    """Treat an omitted location as an instruction not to touch the location field."""
    return str(value or "").strip()


def _navigation_error(page, error):
    detail = str(error or "")
    if "ERR_NETWORK_ACCESS_DENIED" in detail:
        raise RuntimeError(
            "抖音发布页无法访问：浏览器网络连接被系统拒绝（ERR_NETWORK_ACCESS_DENIED）。"
            "请检查 Windows 防火墙、VPN 与安全软件的网络限制后重试。"
        ) from error
    raise error


def _restore_saved_cookies(context):
    """Import only cookies; the saved localStorage crashes this Chrome driver."""
    if not os.path.isfile(STATE_FILE):
        return
    try:
        state = json.loads(Path(STATE_FILE).read_text(encoding="utf-8"))
        cookies = state.get("cookies") or []
        if cookies:
            context.add_cookies(cookies)
    except Exception as exc:
        log(f"⚠️ 无法导入已保存的抖音 Cookie，请重新登录：{exc}")


# ====== 主流程 ======
def publish_video(video_path: str, title: str = None, body: str = None,
                  location: str = None, topics: list = None, dry_run: bool = False,
                  auto_publish: bool = False):
    """上传视频并填表单，停留在发布页"""
    if not os.path.exists(video_path):
        log(f"❌ 视频不存在: {video_path}")
        return False

    video_name = os.path.basename(video_path)
    size_mb = os.path.getsize(video_path) / 1024 / 1024
    title = str(title or DEFAULT_TITLE).strip()
    body = str(body or DEFAULT_BODY).strip()
    location = normalize_location(location)
    topics = list(topics) if topics else list(DEFAULT_TOPICS)

    start_time = time.time()
    log(f"🕵️ dy-video | {video_name} ({size_mb:.1f}MB) | {'试运行' if dry_run else '正式发布'}")

    if dry_run:
        log("🔍 试运行模式：只诊断，不实际上传")
        return True

    with sync_playwright() as p:
        if not BROWSER_EXECUTABLE or not os.path.isfile(BROWSER_EXECUTABLE):
            log("❌ 未找到 Google Chrome；发布器不会回退到 Edge 或 Playwright 浏览器")
            return False
        browser = p.chromium.launch(
            headless=False,
            executable_path=BROWSER_EXECUTABLE,
            ignore_default_args=PLAYWRIGHT_DEFAULT_ARGS_TO_IGNORE,
            args=CHROME_LAUNCH_ARGS,
        )
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        _restore_saved_cookies(context)
        page = prepare_single_visible_page(context, PUBLISH_URL)
        log(f"🌐 已直接打开 Google Chrome: {BROWSER_EXECUTABLE}")

        # === 1. 导航到发布页 ===
        try:
            page.goto(PUBLISH_URL, wait_until='domcontentloaded', timeout=30000)
            keep_only_page(context, page)
            restore_visible_window(page)
        except Exception as exc:
            try:
                browser.close()
            except Exception:
                pass
            _navigation_error(page, exc)
        human_wait(page, 2500, 5000)

        # 关闭初始弹窗
        for t in ['我知道了', '确定', '知道了']:
            try:
                btn = page.query_selector(f'text="{t}"')
                if btn and btn.is_visible(timeout=2000):
                    btn.click()
                    human_wait(page, 300, 500)
            except:
                pass

        # 验证已登录且在视频发布页
        url = page.url
        if 'login' in url.lower():
            log("❌ 未登录，douyin_state.json可能过期")
            return False

        log("1️⃣ 已进入视频发布页")

        # === 2. 上传视频 ===
        # 等待上传区域就绪
        try:
            page.wait_for_selector('input[type="file"]', timeout=15000)
        except:
            log("⚠️ file input未出现，再等5秒")
            human_wait(page, 5000, 5000)
        
        upload_btn = None
        for sel in ['.container-drag-btn-k6XmB4', 'button:has-text("上传视频")',
                    '.semi-button-primary']:
            try:
                upload_btn = page.query_selector(sel)
                if upload_btn and upload_btn.is_visible():
                    break
            except:
                continue

        if upload_btn:
            log("2️⃣ 点击上传按钮")
            with page.expect_file_chooser() as fc_info:
                upload_btn.click()
            file_chooser = fc_info.value
            file_chooser.set_files([video_path])
            log(f"   📹 {video_name} 已提交上传")
        else:
            # 兜底：直接设置 file input
            file_input = page.query_selector('input[type="file"]')
            if file_input:
                log("2️⃣ 兜底：直接通过file input上传")
                file_input.set_input_files([video_path])
                log(f"   📹 {video_name} 已提交（file input兜底）")
            else:
                log("❌ 找不到上传入口")
                # 最后一次诊断
                body = page.evaluate('() => document.body.innerText[:300]')
                log(f"   页面内容: {body}")
                return False

        # === 3. 等待视频处理 ===
        log("⏳ 等待视频处理（15-25秒）...")
        human_wait(page, 8000, 12000)

        # 再次关闭弹窗（视频处理完成后可能弹出）
        for t in ['我知道了', '确定', '知道了']:
            try:
                btn = page.query_selector(f'text="{t}"')
                if btn and btn.is_visible(timeout=2000):
                    btn.click()
                    human_wait(page, 200, 400)
            except:
                pass

        # 等待编辑表单出现
        log("⏳ 等待编辑表单加载...")
        human_wait(page, 8000, 12000)

        # 检查表单是否就绪
        body_text = page.evaluate('() => document.body.innerText')
        form_ready = ('作品描述' in body_text or '填写作品标题' in body_text)
        log(f"📋 表单状态: {'✅ 就绪' if form_ready else '⚠️ 等待中'}")

        if not form_ready:
            human_wait(page, 5000, 10000)

        # === 4. 填标题 ===
        log(f"4️⃣ 标题: {title}")
        title_input = None
        for sel in ['input[placeholder*="填写作品标题"]', 'input[placeholder*="标题"]']:
            try:
                title_input = page.query_selector(sel)
                if title_input and title_input.is_visible():
                    break
            except:
                continue

        if title_input:
            title_input.click()
            human_wait(page, 300, 600)
            title_input.fill(title)
            human_wait(page, 300, 500)
            val = title_input.input_value()
            log(f"   ✅ 标题已填: {val}")
        else:
            log("   ⚠️ 标题输入框未找到")

        # === 5. 填正文 ===
        log("5️⃣ 填写正文...")
        desc_div = None
        for sel in ['.zone-container', '[contenteditable="true"]',
                     '.editor-kit-container', 'div[contenteditable]']:
            try:
                desc_div = page.query_selector(sel)
                if desc_div and desc_div.is_visible():
                    break
            except:
                continue

        if desc_div:
            desc_div.click()
            human_wait(page, 200, 500)
            # 清除现有内容
            page.keyboard.press('Control+a')
            page.keyboard.press('Backspace')
            human_wait(page, 200, 400)

            for line in body.split('\n'):
                human_type(page, line)
                page.keyboard.press('Enter')
                human_wait(page, 100, 300)

            log("   ✅ 正文已填")
        else:
            log("   ⚠️ 正文输入区未找到")

        # === 6. 添加话题标签 ===
        log("6️⃣ 添加话题标签...")
        try:
            topic_btn = page.query_selector('text="#添加话题"')
            if topic_btn and topic_btn.is_visible():
                for topic in topics:
                    topic_btn.click()
                    human_wait(page, 800, 1500)
                    human_type(page, topic)
                    human_wait(page, 800, 1500)
                    page.keyboard.press('Enter')
                    human_wait(page, 500, 1000)
                log(f"   ✅ 已添加 {len(topics)} 个话题")
            else:
                log("   ⚠️ #添加话题按钮未找到，尝试在正文中直接写 #话题")
                # 兜底：在正文末尾添加话题
                if desc_div:
                    desc_div.click()
                    page.keyboard.press('End')
                    human_wait(page, 200, 400)
                    for topic in topics:
                        page.keyboard.press('Enter')
                        human_type(page, f"#{topic}")
                        human_wait(page, 100, 300)
                    log("   ✅ 话题已写入正文")
        except Exception as e:
            log(f"   ⚠️ 话题异常: {e}")

        # === 7. 位置 ===
        if location:
            log(f"7️⃣ 位置: {location}")
            try:
                # 滚动到位置区域
                scrolled = page.evaluate('''() => {
                    const all = document.querySelectorAll('*');
                    for (const el of all) {
                        if ((el.innerText||'').includes('输入地理位置') && el.offsetParent) {
                            el.scrollIntoView({block: 'center'});
                            return 'scrolled';
                        }
                    }
                    for (const el of all) {
                        const txt = (el.innerText||'').trim();
                        if (txt === '位置' && el.offsetParent && el.children.length === 0) {
                            el.scrollIntoView({block: 'center'});
                            return 'scrolled_to_label';
                        }
                    }
                    return 'not_found';
                }''')
                log(f"   滚动: {scrolled}")
                human_wait(page, 500, 1000)

                # 点击"输入地理位置"占位文字触发搜索框
                try:
                    loc_placeholder = page.query_selector('text="输入地理位置"')
                    if loc_placeholder and loc_placeholder.is_visible():
                        loc_placeholder.click()
                        log("   点击了输入地理位置")
                    else:
                        # 找包含"位置"标签的区域点击
                        page.evaluate('''() => {
                            const all = document.querySelectorAll('*');
                            for (const el of all) {
                                const txt = (el.innerText||'').trim();
                                if (txt === '位置' && el.offsetParent && el.children.length === 0) {
                                    el.click();
                                    return;
                                }
                            }
                        }''')
                        log("   点击了位置标签")
                except Exception as e:
                    log(f"   点击异常: {e}")

                human_wait(page, 800, 1500)

                # 直接键盘打字（焦点应该在搜索框上）
                human_type(page, location)
                human_wait(page, 2000, 3000)

                # 选择第一个结果
                page.keyboard.press('ArrowDown')
                human_wait(page, 300, 600)
                page.keyboard.press('Enter')
                human_wait(page, 3000, 5000)

                # 验证
                body_check = page.evaluate('() => document.body.innerText')
                if location in body_check:
                    log("   ✅ 位置已设置")
                else:
                    log("   ⚠️ 位置验证未通过，可能选择失败")
            except Exception as e:
                log(f"   ⚠️ 位置异常: {e}")
        else:
            log("7️⃣ 未填写位置，跳过位置设置")

        # === 8. 封面选择：点击AI推荐的第一张封面 ===
        log("8️⃣ 选择AI推荐封面...")
        try:
            # 等待AI封面生成完成
            human_wait(page, 3000, 5000)
            
            # 点击第一张AI推荐封面
            cover_clicked = page.evaluate('''() => {
                const containers = document.querySelectorAll('[class*="recommendCover"]');
                for (const c of containers) {
                    if (c.offsetParent && c.children.length > 0) {
                        const firstImg = c.children[0];
                        if (firstImg) {
                            firstImg.click();
                            return 'clicked_recommend';
                        }
                    }
                }
                return 'not_found';
            }''')
            log(f"   封面: {cover_clicked}")
            
            # 等待确认弹窗 "是否确认应用此封面"
            human_wait(page, 2000, 4000)
            
            # 用 Playwright locator 找弹窗中的确定按钮
            try:
                dialog = page.locator('.semi-modal-wrap, [role="dialog"]').filter(has_text="封面")
                if dialog.count() > 0:
                    confirm = dialog.locator('button:has-text("确定"), button:has-text("确认")')
                    if confirm.count() > 0:
                        confirm.first.click()
                        human_wait(page, 300, 600)
                        log("   ✅ 封面已确认")
                    else:
                        log("   ℹ️ 弹窗中无确定按钮")
                else:
                    log("   ℹ️ 封面确认弹窗未出现")
            except Exception as e:
                log(f"   ℹ️ 封面确认: {e}")
        except Exception as e:
            log(f"   ⚠️ 封面异常: {e}")

        # === 9. 保存权限：不允许 ===
        log("9️⃣ 保存权限: 不允许")
        try:
            perm_set = page.evaluate('''() => {
                const all = document.querySelectorAll('*');
                for (const el of all) {
                    const txt = (el.innerText||'').trim();
                    if (txt === '不允许' && el.offsetParent && el.children.length === 0) {
                        // 点击"不允许"前面的radio
                        const parent = el.parentElement;
                        if (parent) {
                            const radio = parent.querySelector('input[type="radio"], .radio-native-p6VBGt');
                            if (radio) {
                                radio.click();
                                return 'clicked_radio';
                            }
                        }
                        el.click();
                        return 'clicked_text';
                    }
                }
                return 'not_found';
            }''')
            log(f"   权限: {perm_set}")
        except Exception as e:
            log(f"   ⚠️ 权限异常: {e}")
        # === 10. 自主声明：内容由AI生成 ===
        log("🔟 自主声明: 内容由AI生成")
        try:
            # 点击"添加声明"打开弹窗
            decl_btn = page.locator('text="添加声明"')
            if decl_btn.count() > 0 and decl_btn.first.is_visible():
                decl_btn.first.click()
                human_wait(page, 2000, 3000)
            else:
                log("   声明按钮未找到")
            
            # 在弹窗中勾选"内容由AI生成"
            try:
                is_checked = False
                
                # 方案1: Playwright force click 定位 semi-radio label
                ai_label = page.locator('label.semi-radio, label.semi-checkbox').filter(has_text="内容由AI生成")
                if ai_label.count() > 0:
                    try:
                        ai_label.first.click(force=True, timeout=5000)
                        log("   方案1 force_click_label 已尝试")
                    except Exception as e:
                        log(f"   方案1 异常: {e}")
                
                human_wait(page, 300, 600)
                
                # 验证
                is_checked = page.evaluate('''() => {
                    const labels = document.querySelectorAll('label.semi-radio, label.semi-checkbox');
                    for (const label of labels) {
                        if (label.innerText.includes('内容由AI生成')) {
                            const input = label.querySelector('input[type="radio"], input[type="checkbox"]');
                            if (input) return input.checked;
                            return label.classList.contains('semi-radio-checked') || label.classList.contains('semi-checkbox-checked');
                        }
                    }
                    return false;
                }''')
                
                if not is_checked:
                    # 方案2: JS 直接设置 input.checked + 触发 React 事件
                    log("   ⚠️ 方案1未生效，尝试方案2: JS直接操作")
                    js_result = page.evaluate('''() => {
                        const labels = document.querySelectorAll('label.semi-radio, label.semi-checkbox');
                        for (const label of labels) {
                            if (label.innerText.includes('内容由AI生成')) {
                                const input = label.querySelector('input[type="radio"], input[type="checkbox"]');
                                if (input) {
                                    // 模拟原生点击
                                    const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                                        window.HTMLInputElement.prototype, 'checked'
                                    ).set;
                                    nativeInputValueSetter.call(input, true);
                                    input.dispatchEvent(new Event('click', {bubbles: true}));
                                    input.dispatchEvent(new Event('change', {bubbles: true}));
                                    input.dispatchEvent(new MouseEvent('change', {bubbles: true}));
                                    return 'js_set_checked:' + input.checked;
                                }
                                // 无 input，直接触发 label click
                                label.dispatchEvent(new Event('click', {bubbles: true}));
                                label.dispatchEvent(new MouseEvent('click', {bubbles: true}));
                                return 'js_click_label';
                            }
                        }
                        return 'not_found';
                    }''')
                    log(f"   方案2: {js_result}")
                    
                    human_wait(page, 300, 600)
                    
                    # 再次验证
                    is_checked = page.evaluate('''() => {
                        const labels = document.querySelectorAll('label.semi-radio, label.semi-checkbox');
                        for (const label of labels) {
                            if (label.innerText.includes('内容由AI生成')) {
                                const input = label.querySelector('input[type="radio"], input[type="checkbox"]');
                                if (input) return input.checked;
                                return label.classList.contains('semi-radio-checked') || label.classList.contains('semi-checkbox-checked');
                            }
                        }
                        return false;
                    }''')
                    
                    if not is_checked:
                        # 方案3: 终极兜底 - 找所有可能的点击目标
                        log("   ⚠️ 方案2未生效，尝试方案3: 多目标点击")
                        page.evaluate('''() => {
                            const all = document.querySelectorAll('*');
                            for (const el of all) {
                                if (el.innerText === '内容由AI生成' && el.offsetParent) {
                                    // 点击父级链上的每个元素
                                    let current = el;
                                    while (current && current !== document.body) {
                                        try { current.click(); } catch(e) {}
                                        current = current.parentElement;
                                    }
                                }
                            }
                        }''')
                        human_wait(page, 300, 600)
                        is_checked = page.evaluate('''() => {
                            const labels = document.querySelectorAll('label.semi-radio, label.semi-checkbox');
                            for (const label of labels) {
                                if (label.innerText.includes('内容由AI生成')) {
                                    const input = label.querySelector('input[type="radio"], input[type="checkbox"]');
                                    if (input) return input.checked;
                                    return label.classList.contains('semi-radio-checked') || label.classList.contains('semi-checkbox-checked');
                                }
                            }
                            return false;
                        }''')
                
                log(f"   AI声明最终状态: {'✅ 已勾选' if is_checked else '❌ 未勾选（三方案均失败）'}")
            except Exception as e:
                log(f"   ⚠️ 勾选异常: {e}")
                is_checked = False
            
            # 点击确定关闭弹窗
            human_wait(page, 300, 600)
            closed = page.evaluate('''() => {
                const all = document.querySelectorAll('button');
                for (const btn of all) {
                    const txt = (btn.innerText||'').trim();
                    if (txt === '确定' || txt === '确认') {
                        btn.click();
                        return 'clicked:' + txt;
                    }
                }
                return 'no_btn';
            }''')
            if closed == 'no_btn':
                page.keyboard.press('Escape')
                log("   ✅ 声明弹窗已关闭(Esc)")
            else:
                log(f"   ✅ 声明弹窗: {closed}")
        except Exception as e:
            log(f"   ⚠️ 声明异常: {e}")
            try:
                page.keyboard.press('Escape')
            except:
                pass

        # === 11. 最终检查和截图 ===
        elapsed = time.time() - start_time
        log(f"⏹️ 表单填写完成 | 耗时 {elapsed:.1f}秒")

        import datetime as _dt
        screenshot_dir = os.environ.get("DOUYIN_SCREENSHOT_DIR") or os.path.expanduser(r"~\\.hermes\\logs\\screenshots")
        os.makedirs(screenshot_dir, exist_ok=True)
        ss_ts = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        page.screenshot(
            path=os.path.join(screenshot_dir, f"dy_video_review_{ss_ts}.png"),
            full_page=True
        )
        log(f"   📸 截图: ~/.hermes/logs/screenshots/dy_video_review_{ss_ts}.png")

        # 验证表单完整性
        final_check = page.evaluate('''() => {
            const body = document.body.innerText;
            return {
                has_publish_btn: body.includes('发布'),
                has_title: document.querySelector('input[placeholder*="标题"]') !== null,
                url: window.location.href
            };
        }''')
        if page.is_closed() or "creator.douyin.com" not in str(final_check.get('url') or ''):
            log("❌ 发布页在完成前已关闭或跳转，不能标记为已准备完成")
            return False
        log(f"   发布按钮存在: {'✅' if final_check['has_publish_btn'] else '❌'}")
        log(f"   URL: {final_check['url']}")

        if auto_publish:
            # === 12. 点击发布按钮 ===
            log("🚀 自动发布模式：正在点击发布按钮...")
            human_wait(page, 2000, 4000)
            
            try:
                # 找发布按钮（精确匹配"发布"，排除"高清发布"等）
                import re as _re
                publish_btn = None
                
                # 用 Playwright 精确匹配文本="发布"的按钮
                publish_btn = page.locator('button').filter(has_text=_re.compile(r'^发布$'))
                if publish_btn.count() == 0:
                    publish_btn = page.get_by_text('发布', exact=True).locator('button')
                
                if publish_btn.count() > 0:
                    btn = publish_btn.first
                    btn_text = btn.inner_text().strip()
                    log(f"   发布按钮: '{btn_text}'")
                    
                    # 截图发布前
                    page.screenshot(
                        path=os.path.join(screenshot_dir, f"dy_video_before_publish_{ss_ts}.png"),
                        full_page=True
                    )
                    log("   📸 发布前截图已保存")
                    
                    btn.click()
                    log("   ✅ 已点击发布按钮")
                else:
                    # JS 兜底
                    page.evaluate('''() => {
                        const buttons = document.querySelectorAll('button');
                        for (const btn of buttons) {
                            if ((btn.innerText || '').trim() === '发布') {
                                btn.click();
                                return 'clicked';
                            }
                        }
                        return 'not_found';
                    }''')
                    log("   ✅ 已点击发布按钮（JS兜底）")
                
                # 等待发布处理
                human_wait(page, 5000, 10000)
                
                # 检查发布结果
                page.screenshot(
                    path=os.path.join(screenshot_dir, f"dy_video_after_publish_{ss_ts}.png"),
                    full_page=True
                )
                log("   📸 发布后截图已保存")
                
                body_text = page.evaluate('() => document.body.innerText')
                if '发布成功' in body_text or '审核中' in body_text or '已发布' in body_text:
                    log("   🎉 发布成功！")
                elif '失败' in body_text or '错误' in body_text:
                    log("   ⚠️ 发布可能失败，请检查浏览器")
                else:
                    log("   ℹ️ 发布状态未知（可能跳转到作品管理页）")
            except Exception as e:
                log(f"   ❌ 发布异常: {e}")
            
            # 保持浏览器打开30秒供查看
            log("⏸️ 30秒后自动关闭浏览器...")
            try:
                page.wait_for_timeout(30000)
            except:
                pass
        else:
            log(f"   🔴 停留在发布页，等待审核！")
            log("✅ 发布页已准备完成，Google Chrome 将保持打开供人工审核。")
            # The upstream publisher keeps its direct Playwright-launched
            # browser alive for manual review.  Returning here would close the
            # only Chrome window as the Playwright process exits.
            try:
                page.wait_for_timeout(1200000)
            except Exception as exc:
                _raise_if_publish_window_closed(page, exc)
                raise
        
        try:
            browser.close()
        except Exception:
            pass

    return True


def main():
    parser = argparse.ArgumentParser(description='抖音视频发布（填表后等待审核）')
    parser.add_argument('video', help='视频文件路径')
    parser.add_argument('--title', help='标题（默认30字以内）')
    parser.add_argument('--body', help='正文')
    parser.add_argument('--location', default=LOCATION, help='位置')
    parser.add_argument('--topics', default='', help='话题标签，使用逗号或空格分隔')
    parser.add_argument('--dry-run', action='store_true', help='试运行模式')
    parser.add_argument('--publish', action='store_true', help='自动点击发布（默认只填表不发布）')
    args = parser.parse_args()

    try:
        success = publish_video(
            video_path=args.video,
            title=args.title,
            body=args.body,
            location=args.location,
            topics=[item.strip().lstrip('#') for item in re.split(r'[\s,，、]+', args.topics) if item.strip()] or None,
            dry_run=args.dry_run,
            auto_publish=args.publish
        )
    except Exception as exc:
        if _is_target_closed_error(exc) or isinstance(exc, UserClosedPublishWindow):
            log(f"⏹️ {USER_CLOSED_WINDOW_MESSAGE}")
            print(USER_CLOSED_WINDOW_MARKER, flush=True)
            return 2
        raise
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())
