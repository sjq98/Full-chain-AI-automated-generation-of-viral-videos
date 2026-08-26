#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频号运营数据采集器。

功能：
1. 抓"单篇视频" tab 的每个视频数据（完播率/平均时长/播放/点赞/评论/分享/关注）
2. 抓"全部视频" tab 的汇总数据（关键指标 + 流量来源占比）
3. 写入本地 CSV：data/stats/yyyy-mm-dd.csv

用法：
  python scripts/collect_stats.py              # 默认：全部视频 + 近 7 天
  python scripts/collect_stats.py --days 1     # 近 1 天
  python scripts/collect_stats.py --days 30    # 近 30 天
"""
import argparse
import asyncio
import csv
import sys
from datetime import datetime
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("错误：未安装 playwright")
    sys.exit(1)

USER_DATA_DIR = Path(__file__).parent.parent / "browser_data"
STATS_DIR = Path(__file__).parent.parent / "data" / "stats"
STATS_DIR.mkdir(parents=True, exist_ok=True)

DATA_URL = "https://channels.weixin.qq.com/platform/statistic/post"


async def dismiss_first_time_dialog(target):
    """首次访问可能弹"暂时无法使用"提示，点击确定关闭。"""
    try:
        btn = target.locator('text=我知道了').first
        if await btn.count():
            await btn.click(timeout=3000)
            await asyncio.sleep(1)
    except Exception:
        pass


async def switch_tab(target, tab_index: int):
    """切 tab（0=全部视频, 1=单篇视频）。

    Tab 在 iframe 'micro/statistic/post' 里，ul.weui-desktop-tab__navs__inner > li。
    """
    try:
        ok = await target.evaluate(f"""
        () => {{
            const lis = document.querySelectorAll('.weui-desktop-tab__navs__inner > li');
            if (lis.length > {tab_index}) {{
                lis[{tab_index}].click();
                return true;
            }}
            return false;
        }}
        """)
        if ok:
            await asyncio.sleep(2)
            return True
        print(f"  ⚠️ 切 tab[{tab_index}] 失败：tab 数量不足")
        return False
    except Exception as e:
        print(f"  ⚠️ 切 tab[{tab_index}] 失败: {e}")
        return False


async def collect_single_videos(target, days: int = 7):
    """采集单视频数据：每个视频一行。

    表格列（按索引）:
      [0] 视频标题, [1] 发布时间, [2] 完播率, [3] 平均播放时长,
      [4] 播放, [5] 点赞(❤), [6] 喜欢(👍), [7] 评论, [8] 关注, [9] 分享,
      [10] 转发聊天和朋友圈, [11] 设为铃声, [12] 设为状态, [13] 设为朋友圈封面,
      [14] 企微链接点击次数, [15] 企微链接点击人数,
      [16] 添加到通讯录次数, [17] 添加到通讯录人数, [18] 详情按钮
    """
    # 切到"单篇视频" tab（index=1）
    ok = await switch_tab(target, 1)
    if not ok:
        return []
    await dismiss_first_time_dialog(target)

    # 设日期范围
    label = "近7天" if days == 7 else ("近30天" if days == 30 else f"近{days}天")
    try:
        await target.evaluate(f"""
        () => {{
            const all = document.querySelectorAll('li, [class*=tab] > *, span, div');
            for (const el of all) {{
                if ((el.innerText || '').trim() === '{label}') {{
                    el.click();
                    return true;
                }}
            }}
            return false;
        }}
        """)
        await asyncio.sleep(2)
    except Exception:
        pass  # 默认就是近7天

    # 抓表格行（过滤掉 header：含"视频"但不以"第"开头的）
    rows = await target.evaluate("""
    () => {
        const trs = document.querySelectorAll('tr');
        const out = [];
        for (const tr of trs) {
            const tds = tr.querySelectorAll('td');
            if (tds.length < 5) continue;
            const firstTdText = (tds[0].innerText || '').trim();
            // 只保留数据行（第一格以"第"开头 = 视频标题）
            if (!firstTdText.match(/^第\\d+章/)) continue;
            const texts = [];
            for (const td of tds) texts.push((td.innerText || '').trim());
            out.push(texts);
        }
        return out;
    }
    """)

    print(f"  单视频抓取行数: {len(rows)}")
    parsed = []
    for row in rows:
        try:
            import re
            m = re.search(r'第(\d+)章', row[0])
            if not m:
                continue
            chapter = int(m.group(1))
            data = {
                'chapter': chapter,
                'publish_date': row[1] if len(row) > 1 else '',
                'completion_rate': row[2] if len(row) > 2 else '',
                'avg_play_sec': row[3] if len(row) > 3 else '',
                'plays': row[4] if len(row) > 4 else '',
                'likes': row[5] if len(row) > 5 else '',     # ❤
                'likes_v2': row[6] if len(row) > 6 else '',  # 👍
                'comments': row[7] if len(row) > 7 else '',
                'follows': row[8] if len(row) > 8 else '',
                'shares': row[9] if len(row) > 9 else '',
                'forward_chat': row[10] if len(row) > 10 else '',
                'set_ringtone': row[11] if len(row) > 11 else '',
                'set_status': row[12] if len(row) > 12 else '',
                'set_cover': row[13] if len(row) > 13 else '',
                'link_clicks_total': row[14] if len(row) > 14 else '',
                'link_clicks_unique': row[15] if len(row) > 15 else '',
                'add_to_contacts_total': row[16] if len(row) > 16 else '',
                'add_to_contacts_unique': row[17] if len(row) > 17 else '',
            }
            parsed.append(data)
        except Exception as e:
            print(f"  解析行失败: {e} -> {row}")
    return parsed


async def collect_overview(target, days: int = 7):
    """采集全部视频汇总（关键指标 6 个数字）。"""
    await switch_tab(target, 0)  # 全部视频 tab

    overview = await target.evaluate("""
    () => {
        const out = {};
        // 关键指标是数字，每个数字配一个 label（播放/点赞/喜欢/评论/分享/关注）
        const labels = ['plays', 'likes', 'likes_v2', 'comments', 'shares', 'follows'];
        const keywords = ['播放', '点赞', '喜欢', '评论', '分享', '关注'];
        // 找标签和数字对
        const items = document.querySelectorAll('[class*=key], [class*=indicator], [class*=card], [class*=item]');
        const result = [];
        for (const it of items) {
            const t = (it.innerText || '').trim();
            if (t.match(/^\\d+$/) || t.match(/^\\d+\\.\\d+%$/)) {
                // 纯数字
                result.push(t);
            }
        }
        // 也直接找表格
        const tds = document.querySelectorAll('td');
        for (const td of tds) {
            const t = (td.innerText || '').trim();
            if (t.match(/^\\d+$/)) {
                result.push(t);
            }
        }
        return result;
    }
    """)
    print(f"  全部视频关键指标: {overview}")
    return overview


async def collect_traffic_source(target, days: int = 7):
    """采集流量来源占比。"""
    await target.evaluate("window.scrollTo(0, document.body.scrollHeight)")
    await asyncio.sleep(2)
    sources = await target.evaluate("""
    () => {
        const out = {};
        const sourceNames = ['关注', '朋友', '推荐', '分享', '订阅号消息', '主页', '其他'];
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.children.length > 0) continue;
            const t = (el.innerText || '').trim();
            const pctMatch = t.match(/^([\\d.]+)%$/);
            if (!pctMatch) continue;
            let prev = el.previousElementSibling;
            for (let i = 0; i < 5 && prev; i++) {
                const pt = (prev.innerText || '').trim();
                if (sourceNames.includes(pt)) {
                    out[pt] = pctMatch[1] + '%';
                    break;
                }
                prev = prev.previousElementSibling;
            }
        }
        return out;
    }
    """)
    print(f"  流量来源占比: {sources}")
    return sources


def parse_pct(s: str) -> float:
    """'20.16%' -> 20.16"""
    if not s:
        return 0.0
    s = s.replace('%', '').strip()
    try:
        return float(s)
    except ValueError:
        return 0.0


def parse_seconds(s: str) -> float:
    """'6.12秒' -> 6.12"""
    if not s:
        return 0.0
    import re
    m = re.search(r'([\d.]+)秒', s)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return 0.0
    return 0.0


def parse_int(s: str) -> int:
    """'265' -> 265, '+6525%' -> 6525"""
    if not s:
        return 0
    import re
    m = re.search(r'(\d[\d,]*)', s.replace(',', ''))
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            return 0
    return 0


def save_to_csv(rows: list, overview: dict, sources: dict, days: int):
    """写入 CSV。"""
    today = datetime.now().strftime("%Y-%m-%d")
    csv_path = STATS_DIR / f"{today}_days{days}.csv"

    fieldnames = [
        'collect_date', 'days_window', 'chapter', 'publish_date',
        'plays', 'likes', 'likes_v2', 'comments', 'follows', 'shares',
        'forward_chat', 'set_ringtone', 'set_status', 'set_cover',
        'link_clicks_total', 'link_clicks_unique',
        'add_to_contacts_total', 'add_to_contacts_unique',
        'completion_rate_pct', 'avg_play_sec',
        'source_follow_pct', 'source_friend_pct', 'source_recommend_pct',
        'source_share_pct', 'source_msg_pct', 'source_page_pct', 'source_other_pct',
    ]

    file_exists = csv_path.exists()
    with open(csv_path, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        for r in rows:
            row = {
                'collect_date': today,
                'days_window': days,
                'chapter': r['chapter'],
                'publish_date': r['publish_date'],
                'plays': parse_int(r['plays']),
                'likes': parse_int(r['likes']),
                'likes_v2': parse_int(r['likes_v2']),
                'comments': parse_int(r['comments']),
                'follows': parse_int(r['follows']),
                'shares': parse_int(r['shares']),
                'forward_chat': parse_int(r['forward_chat']),
                'set_ringtone': parse_int(r['set_ringtone']),
                'set_status': parse_int(r['set_status']),
                'set_cover': parse_int(r['set_cover']),
                'link_clicks_total': parse_int(r['link_clicks_total']),
                'link_clicks_unique': parse_int(r['link_clicks_unique']),
                'add_to_contacts_total': parse_int(r['add_to_contacts_total']),
                'add_to_contacts_unique': parse_int(r['add_to_contacts_unique']),
                'completion_rate_pct': parse_pct(r['completion_rate']),
                'avg_play_sec': parse_seconds(r['avg_play_sec']),
                'source_follow_pct': parse_pct(sources.get('关注', '')),
                'source_friend_pct': parse_pct(sources.get('朋友', '')),
                'source_recommend_pct': parse_pct(sources.get('推荐', '')),
                'source_share_pct': parse_pct(sources.get('分享', '')),
                'source_msg_pct': parse_pct(sources.get('订阅号消息', '')),
                'source_page_pct': parse_pct(sources.get('主页', '')),
                'source_other_pct': parse_pct(sources.get('其他', '')),
            }
            writer.writerow(row)

    print(f"\n✅ 已保存 {len(rows)} 行到: {csv_path}")


async def main():
    parser = argparse.ArgumentParser(description="视频号运营数据采集")
    parser.add_argument("--days", type=int, default=7, choices=[1, 7, 30],
                        help="采集时间窗口（1=近1天, 7=近7天, 30=近30天）")
    args = parser.parse_args()

    print("=" * 60)
    print("视频号运营数据采集")
    print("=" * 60)
    print(f"时间窗口: 近 {args.days} 天")
    print()

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,
            no_viewport=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.bring_to_front()

        print(f"打开数据后台: {DATA_URL}")
        await page.goto(DATA_URL, timeout=60000, wait_until="domcontentloaded")
        await asyncio.sleep(5)

        # 检测登录态
        if "login" in page.url or "passport" in page.url:
            print("❌ Cookie 失效，请先跑 get_cookie.py 扫码登录")
            await ctx.close()
            return

        # 数据后台在 iframe 'micro/statistic/post' 里，不在 page 上
        target = None
        for f in page.frames:
            if 'micro/statistic' in f.url:
                target = f
                break
        if not target:
            print("❌ 找不到 'micro/statistic/post' iframe")
            await ctx.close()
            return

        # 1) 抓单视频数据
        print("\n[1/3] 抓取单视频数据...")
        rows = await collect_single_videos(target, days=args.days)

        # 2) 抓全部视频汇总
        print("\n[2/3] 抓取全部视频汇总...")
        overview = await collect_overview(target, days=args.days)

        # 3) 抓流量来源
        print("\n[3/3] 抓取流量来源占比...")
        sources = await collect_traffic_source(target, days=args.days)

        # 截图存证
        logs_dir = Path(__file__).parent.parent / "logs"
        logs_dir.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        try:
            await page.screenshot(path=str(logs_dir / f"stats-{stamp}.png"), full_page=True)
            print(f"\n📸 截图: logs/stats-{stamp}.png")
        except Exception as e:
            print(f"截图失败: {e}")

        # 4) 写 CSV
        if rows:
            save_to_csv(rows, overview, sources, args.days)
        else:
            print("\n⚠️  没抓到任何单视频数据，CSV 未写入")

        print()
        print("=" * 60)
        print("✅ 采集完成")
        print("=" * 60)

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())