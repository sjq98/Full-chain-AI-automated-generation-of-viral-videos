"""
dy-video 主入口：选视频 → 发布到抖音
从素材目录每日选2个视频，调用 dy_video_publish.py 发布
已发标记：文件名加（已发）后缀，如 "1 (2)（已发）.mp4"
"""
import os, sys, time, re, argparse
from pathlib import Path

# === 配置 ===
VIDEO_DIR = r"D:\BaiduSyncdisk\8 本地推素材\@自动发图文素材库\抖音AI成片\成片"
POSTED_SUFFIX = "（已发）"

# 两套爆款文案（交替使用）
TEMPLATES = [
    {
        "title": "爸妈出门不便？租轮椅就够",
        "body": "爸妈腿脚不好、术后康复、临时受伤\n不用花几千买轮椅！佳康顺日租超省钱\n\n每天几块钱，全新轮椅送到家\n苏州昆山通借通还，随租随用超方便\n\n用完即还，无隐形消费\n点主页咨询，马上安排～",
    },
    {
        "title": "不用买轮椅！日租几块钱",
        "body": "出门腿脚不便的痛，经历过才懂\n但真不用花大几千买轮椅！\n\n佳康顺轮椅日租，每天几块钱\n全新消毒，苏州昆山通借通还\n受伤、康复、老人代步统统搞定\n\n随租随还超灵活，点主页马上咨询～",
    },
]


def list_all_videos():
    """列出目录中所有 mp4 文件（含已发的），按名排序"""
    if not os.path.isdir(VIDEO_DIR):
        return []
    return sorted([
        f for f in os.listdir(VIDEO_DIR)
        if f.lower().endswith('.mp4')
    ])


def list_available_videos():
    """列出未发布的 mp4 文件（文件名不含'（已发）'）"""
    return [v for v in list_all_videos() if POSTED_SUFFIX not in v]


def list_posted_videos():
    """列出已发布的 mp4 文件（文件名含'（已发）'）"""
    return [v for v in list_all_videos() if POSTED_SUFFIX in v]


def select_videos(count=2):
    """从素材目录中选择未发布的视频"""
    if not os.path.isdir(VIDEO_DIR):
        print(f"❌ 素材目录不存在: {VIDEO_DIR}")
        return []

    all_videos = list_all_videos()
    available = list_available_videos()
    posted = list_posted_videos()

    if not available:
        print("🔄 所有视频已发完一轮！需要手动去掉（已发）标记或添加新视频")
        return []

    selected = available[:count]

    if len(selected) < count:
        print(f"⚠️ 只有 {len(selected)} 个可用视频（需要 {count} 个）")

    print(f"📁 素材目录: {VIDEO_DIR}")
    print(f"   总视频数: {len(all_videos)} | 已发: {len(posted)} | 可选: {len(available)}")
    print(f"   本次选择: {selected}")

    return [os.path.join(VIDEO_DIR, v) for v in selected]


def mark_posted(video_name):
    """标记视频为已发布——在文件名中加（已发）后缀"""
    video_path = os.path.join(VIDEO_DIR, video_name)
    if not os.path.exists(video_path):
        print(f"   ⚠️ 文件不存在，无法标记: {video_path}")
        return

    base, ext = os.path.splitext(video_name)
    # 如果已经有后缀则不重复加
    if POSTED_SUFFIX in base:
        print(f"   ℹ️ 已标记过: {video_name}")
        return

    new_name = f"{base}{POSTED_SUFFIX}{ext}"
    new_path = os.path.join(VIDEO_DIR, new_name)
    os.rename(video_path, new_path)
    print(f"   ✅ 已标记: {video_name} → {new_name}")


def get_template():
    """获取当前文案模板——根据已发数量轮换"""
    posted_count = len(list_posted_videos())
    idx = posted_count % len(TEMPLATES)
    return TEMPLATES[idx]


def main():
    parser = argparse.ArgumentParser(description='抖音视频发布（选片+发布）')
    parser.add_argument('--count', type=int, default=2, help='发布视频数量（默认2）')
    parser.add_argument('--dry-run', action='store_true', help='试运行（不实际上传）')
    parser.add_argument('--index', type=int, default=0, help='发布第几个视频（0开始）')
    parser.add_argument('--publish', action='store_true', help='自动点击发布按钮')
    args = parser.parse_args()

    # 选视频
    videos = select_videos(count=args.count)
    if not videos:
        print("❌ 没有可选视频")
        sys.exit(1)

    if args.index >= len(videos):
        print(f"❌ 序号超出范围: {args.index}（共 {len(videos)} 个）")
        sys.exit(1)

    video_path = videos[args.index]
    video_name = os.path.basename(video_path)
    template = get_template()

    print(f"\n🎬 发布视频 [{args.index + 1}/{len(videos)}]: {video_name}")
    print(f"📝 标题: {template['title']}")

    if args.dry_run:
        print("🔍 试运行模式")
        return

    # 导入发布脚本
    script_dir = os.path.dirname(os.path.abspath(__file__))
    sys.path.insert(0, script_dir)
    from dy_video_publish import publish_video

    success = publish_video(
        video_path=video_path,
        title=template["title"],
        body=template["body"],
        auto_publish=args.publish,
    )

    if success:
        mark_posted(video_name)
        print(f"✅ {video_name} 发布流程完成")
    else:
        print(f"❌ {video_name} 发布失败")
        sys.exit(1)


if __name__ == '__main__':
    main()
