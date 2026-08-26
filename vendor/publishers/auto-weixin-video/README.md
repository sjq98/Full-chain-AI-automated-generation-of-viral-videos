# auto-weixin-video

基于 Playwright 的微信视频号自动化发布工具。

> 已验证：单条视频从上传到发表大约 1 分 30 秒，可以批量跑、设定时发表、自动勾选"声明原创"和"含 AI 生成内容"标注。

## 核心功能

- ✅ 视频上传（支持 .mp4）
- ✅ 标题、话题、短标题自动填写
- ✅ 合集选择（可选）
- ✅ **自定义封面上传**（9:16、含中国红编号）
- ✅ **声明原创**（含"原创权益"弹窗自动确认）
- ✅ **视频标注**（自动勾选"含 AI 生成内容"）
- ✅ **定时发布**（指定未来时间发表）
- ✅ Cookie 持久化（重启不丢登录态）

## 工作原理

视频号没有开放 API，所以走 Playwright 浏览器自动化方案：

1. **登录态**：用 `launch_persistent_context` 把 Chromium 的整个用户数据持久化到 `browser_data/` 目录。Cookie、localStorage 都自动保留。
2. **页面元素**：视频号是 Ant Design + iframe 嵌套 + React 受控组件。`publish.py` 里写死了实测可用的 selector。
3. **发布流程**：上传视频 → 填标题/话题 → 自动勾选声明原创（含弹窗确认） → 自动勾选 AI 标注 → 自动上传封面 → 自动点发表。

## 项目结构

```
auto-weixin-video/
├── scripts/
│   ├── get_cookie.py    # 首次登录拿 cookie
│   ├── publish.py       # 单视频发布（核心）
│   └── batch_publish.py # 批量发布（按 CSV 调度）
├── cookies/             # 登录态（不要提交到 git）
├── browser_data/        # Chromium 用户数据（不要提交）
├── logs/                # 调试日志和截图（不要提交）
└── .gitignore
```

## 快速开始

### 1. 安装依赖

```bash
pip install playwright pillow
playwright install chromium
```

### 2. 首次登录拿 Cookie

```bash
python scripts/get_cookie.py
```

会弹出浏览器，微信扫码即可。Cookie 自动保存到 `cookies/weixin_video.json`，下次不用再扫。

### 3. 单视频发布

```bash
python scripts/publish.py \
  -v D:/videos/6.mp4 \
  -t "第06章 天下之至柔" \
  -g "#帛书版道德经 #正能量 #经典阅读 #国学" \
  -o \
  --cover cover-06.jpg \
  --mark-ai \
  -s "2026-08-01 21:30"
```

参数说明：
- `-v` 视频文件路径
- `-t` 标题
- `-g` 话题（空格分隔，代码会自动加 `#`）
- `-o` 声明原创
- `--cover` 封面图片路径（9:16，1080x1920）
- `--mark-ai` 勾选"含 AI 生成内容"
- `-s` 定时发布时间，格式 `YYYY-MM-DD HH:MM`
- `--skip-publish` 调试模式：跑完所有步骤但不点发表
- `--manual-finish` 半自动：跑完机械操作后保留浏览器，由用户手动点发表

### 4. 批量发布

准备 `schedule.csv`：

```csv
video_file,title,description,tags,scheduled_at,published_at,status
1.mp4,第01章 ...,...,#话题 #话题,2026-07-26 21:30,,done
2.mp4,第02章 ...,...,#话题 #话题,2026-07-27 21:30,,pending
```

跑批量：

```bash
python scripts/batch_publish.py --max-count 5
```

自动按 CSV 调度，发布成功后把 `status` 改成 `done`。

## 关键技术点

### React 受控组件
视频号的 checkbox 都是 React 受控的，纯 JS `.click()` 不会更新 React 状态。必须用 Playwright 真点击 wrapper：

```python
await wrapper_loc.click(force=True)
```

### iframe vs 主 frame
- 视频上传、标题/话题/封面 UI：都在 iframe `micro/content/post/create` 里
- **"原创权益"弹窗、AI 标注**：`page` 上能找到（不在 iframe 里）

### 探测已勾选状态
视频号勾选成功后 className 包含：
- Ant Design checkbox：`ant-checkbox-wrapper-checked`
- AI 标注自定义 div：`mark-tag-option is-selected`

只用 `checked` 属性探测不可靠，要看 className。

### `networkidle` 永远等不到
视频号页面一直有心跳包，必须用 `wait_until="domcontentloaded"` + 手动等 iframe 出现。

### 定时发布（2026-07-31 重写）
之前定时控件都用 `page` 找，但 picker / radio / 时间 input 实际**在 iframe `micro/content/post/create` 里**。新方案：

```python
target = next((f for f in page.frames if "micro/content/post/create" in f.url), page)
```

6 步全用 JS evaluate（避开 Playwright stale locator）：

1. 切到"定时"radio（label 文字是"定时"，不是"定时发布"）— React setter 强制改 `checked` + dispatch `click`/`change`
2. JS `focus() + click()` 触发日期 picker（Playwright 真点击会超时）
3. 切月份：`.weui-desktop-picker__panel__hd .weui-desktop-btn__icon__right`（不是 `.weui-desktop-picker__next`）
4. 点日期：`.weui-desktop-picker__table a` 里找精确文字（不是 `weui-desktop-picker__disabled`）
5. 改时间：React setter 改 `input[placeholder="请选择时间"]` 的 value（**全局找**，不在 picker 容器下）+ 触发 `input`/`change`/`blur`
6. 验证：读 `input[placeholder="请选择发表时间"]` 的最终 value

月份切换后 React 会重渲染，Playwright `target.locator(...)` 引用会失效，必须用 `target.evaluate("() => document.querySelector(...)")` 重新查。

批量调度时跳过未来时间过滤：
```bash
python scripts/batch_publish.py --ignore-time --max-count 5
```

## 已知坑

1. **系统重启后需要重新扫码** — browser_data 不一定能跨重启续期
2. **视频号 UI 选择器经常变** — UI 改版后 selector 可能失效，需要更新
3. **`page.pause()` 不靠谱** — 远程桌面下 Playwright Inspector 窗口可能被挡住，扫码后忘了点 Resume 就卡死
4. **登录 cookie 1-2 周失效** — 失效后重新跑 `get_cookie.py`
5. **月份切换按钮 class 经常被混淆** — `weui-desktop-picker__next` 是错的，正确的是 `.weui-desktop-picker__panel__hd .weui-desktop-btn__icon__right`

## License

MIT