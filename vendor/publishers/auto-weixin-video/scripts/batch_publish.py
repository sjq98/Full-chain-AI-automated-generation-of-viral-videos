#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量发布包装器：从 shipinhao-automation/schedule.csv 读条目，
对 status=pending 且到时间的行调用同目录的 publish.py，
自动生成封面（来自 shipinhao-automation/utils.py）+ 启用 -o / --mark-ai。

用法：
    python batch_publish.py                # 处理所有到时间的 pending 行
    python batch_publish.py --file 5.mp4   # 只处理指定视频文件
    python batch_publish.py --dry-run      # 只打印不实际发布
"""
from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# --- 路径：把 shipinhao-automation 加进 sys.path 以复用 utils.generate_cover ---
SCRIPT_DIR = Path(__file__).resolve().parent
AUTO_DIR = SCRIPT_DIR.parent
PROJECT_ROOT = AUTO_DIR.parent  # C:\...\2026-07-31-13-17-15\
SHIPINHAO_DIR = PROJECT_ROOT / "shipinhao-automation"
SCHEDULE_CSV = SHIPINHAO_DIR / "schedule.csv"
VIDEOS_DIR = SHIPINHAO_DIR / "videos"

if str(SHIPINHAO_DIR / "scripts") not in sys.path:
    sys.path.insert(0, str(SHIPINHAO_DIR / "scripts"))
try:
    from utils import generate_cover, extract_chapter  # noqa: E402
except ImportError as e:
    print(f"❌ 无法导入 shipinhao-automation 的 utils：{e}")
    print("   请确认 shipinhao-automation/scripts/utils.py 存在")
    sys.exit(1)

PUBLISH_PY = SCRIPT_DIR / "publish.py"


def parse_scheduled_at(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            continue
    return None


def read_schedule() -> list[dict]:
    if not SCHEDULE_CSV.exists():
        print(f"❌ 找不到 schedule.csv：{SCHEDULE_CSV}")
        sys.exit(1)
    with SCHEDULE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_schedule(rows: list[dict]) -> None:
    fields = ["video_file", "title", "description", "topics",
              "scheduled_at", "duration_sec", "status",
              "published_at", "note"]
    with SCHEDULE_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def mark_published(rows: list[dict], video_file: str) -> None:
    for r in rows:
        if r["video_file"] == video_file:
            r["status"] = "done"
            r["published_at"] = datetime.now().strftime("%Y-%m-%d")
            return


def publish_one(row: dict, dry_run: bool = False, skip_publish: bool = False, keep_browser: int = 0, manual_finish: bool = False, no_location: bool = False) -> bool:
    """调用同目录 publish.py 发布一条视频。返回是否成功。"""
    video_file = row["video_file"].strip()
    title = row["title"].strip()
    topics_raw = row["topics"].strip()
    scheduled_at = row["scheduled_at"].strip()

    # 1) 生成封面（章节号来自视频文件名）
    chapter = extract_chapter(video_file)
    cover_path = None
    if chapter is not None:
        try:
            cover_path = generate_cover(chapter)
            print(f"[封面] 已生成：{cover_path.name}")
        except Exception as e:
            print(f"[封面] 生成失败：{e}")
    else:
        print(f"[封面] 未能从 {video_file} 提取章节号，跳过封面")

    # 2) 构造 CLI 参数
    cmd = [
        sys.executable,
        str(PUBLISH_PY),
        "-v", str(VIDEOS_DIR / video_file),
        "-t", title,
        "-g", topics_raw,
        "-o",  # 声明原创
        "--mark-ai",  # 标注含 AI 生成内容
    ]
    if cover_path:
        cmd += ["--cover", str(cover_path)]
    if scheduled_at:
        cmd += ["-s", scheduled_at]
    if dry_run or skip_publish:
        cmd += ["--skip-publish"]  # 不论 dry-run 还是显式 skip-publish，都不真发
    if keep_browser > 0:
        cmd += ["--keep-browser", str(keep_browser)]
    if manual_finish:
        cmd += ["--manual-finish"]
        if keep_browser == 0:
            cmd += ["--keep-browser", "300"]  # manual-finish 默认 5 分钟
    if no_location:
        cmd += ["--no-location"]

    print()
    print("=" * 60)
    print(f"准备发布：{video_file}")
    print(f"  标题:   {title}")
    print(f"  话题:   {topics_raw}")
    print(f"  章节:   {chapter}")
    print(f"  封面:   {cover_path}")
    print(f"  定时:   {scheduled_at or '立即'}")
    print(f"  模式:   {'dry-run' if dry_run else ('skip-publish' if skip_publish else '正式发布')}")
    print(f"  命令:   {' '.join(cmd[:6])} ...")
    print("=" * 60)

    if dry_run:
        print("[dry-run] 跳过实际发布")
        return True

    # 3) 执行
    try:
        ret = subprocess.run(cmd, check=False)
        return ret.returncode == 0
    except Exception as e:
        print(f"❌ 发布异常：{e}")
        return False


def main():
    parser = argparse.ArgumentParser(description="批量发布道德经视频到视频号")
    parser.add_argument("--file", default=None, help="只发布指定 video_file（如 5.mp4）")
    parser.add_argument("--dry-run", action="store_true", help="只打印要发的内容，不实际执行")
    parser.add_argument("--skip-publish", action="store_true", help="跑完所有步骤但不点发表（保留页面供检查）")
    parser.add_argument("--keep-browser", type=int, default=0, metavar="SEC", help="跑完后保留浏览器 N 秒（默认 0=立即关）")
    parser.add_argument("--manual-finish", action="store_true", help="半自动模式：跑完自动部分后保留浏览器，老K手动勾原创/AI/发表")
    parser.add_argument("--ignore-time", action="store_true", help="忽略定时时间过滤（提前上传+设定时发布，常和 pending 重发一起用）")
    parser.add_argument("--no-location", action="store_true", help="不显示位置（清空'广州市'等默认位置）")
    parser.add_argument("--max-count", type=int, default=0, metavar="N", help="最多发布 N 条（0=不限制）")
    args = parser.parse_args()

    rows = read_schedule()
    print(f"共读取 {len(rows)} 条记录")

    # 过滤要处理的行
    now = datetime.now()
    targets: list[dict] = []
    for r in rows:
        # --file 显式指定时忽略 status（用户明确要发）
        if not args.file and r.get("status", "").strip() != "pending":
            continue
        if args.file and r["video_file"] != args.file:
            continue
        # 如果有定时发布且未到时间，跳过
        # manual-finish / --ignore-time 模式忽略时间过滤（提前上传+设定时发布）
        if not (args.manual_finish or args.ignore_time):
            sched = parse_scheduled_at(r.get("scheduled_at", ""))
            if sched and sched > now and not args.file:
                print(f"  ⏳ {r['video_file']} 定时 {sched} 未到，跳过")
                continue
        targets.append(r)

    # --max-count 限制数量
    if args.max_count > 0:
        targets = targets[:args.max_count]

    if not targets:
        print("✅ 没有需要发布的视频")
        return

    print(f"将处理 {len(targets)} 条：")
    for r in targets:
        print(f"  - {r['video_file']}  {r['title'][:30]}")
    print()

    # 逐条发布
    success_count = 0
    for i, r in enumerate(targets, 1):
        if len(targets) > 1:
            print(f"\n{'='*60}")
            print(f"📺 第 {i}/{len(targets)} 个：{r['video_file']}")
            print(f"{'='*60}")
        ok = publish_one(r, dry_run=args.dry_run, skip_publish=args.skip_publish, keep_browser=args.keep_browser, manual_finish=args.manual_finish, no_location=args.no_location)
        if ok:
            # dry-run / skip-publish 都不该改 CSV
            if not args.dry_run and not args.skip_publish:
                mark_published(rows, r["video_file"])
                write_schedule(rows)
            success_count += 1
        else:
            print(f"❌ {r['video_file']} 发布失败，继续下一条")

    print()
    print(f"完成：{success_count}/{len(targets)} 成功")


if __name__ == "__main__":
    main()