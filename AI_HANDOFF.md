# MP4 金句片段筛选导出工作台 - AI 接管文档

更新时间：2026-08-05  
项目目录：`C:\Users\Neko\Documents\Codex\2026-07-30\mp4-deepseek-mp4-sop`  
当前主服务：`http://127.0.0.1:8767/`  
当前前端脚本版本：`/static/app.js?v=rt37`  
GitHub 仓库：`https://github.com/Neko-2077/mp4-golden-clip-workbench`（public）

> 这份文档用于让其他 AI 或开发者顺利接管本项目继续开发。请优先读取本文件，再看 `app.py`、`static/index.html`、`static/app.js`、`static/app.css`。

## 0. 重大更新（2026-08-05）

### 0.1 移除本地 Whisper 转写

- 用户决策：**只保留火山引擎转写**，放弃本地 Whisper。
- 已删除：`local_transcribe_worker`、`TRANSCRIBE_PRESETS`、`resolve_transcribe_preset`、health check 里的 whisper、`handle_transcribe_start` 和 retry 里的 local 分支。
- `transcribe_worker` 现在无条件走 `volcengine_transcribe_worker`。
- `requirements.txt` 只剩 `tos>=2.9.0`（opencc 也删了，只被 whisper 用过）。
- 前端本来就只有火山 UI（`transcribeEngine` 隐藏 input 固定 `volcengine_bigmodel`）。

### 0.2 Electron 桌面版（desktop/）

- 新增 `desktop/`：Electron 33 + electron-builder 25 + electron-updater 6 打包的桌面应用。
- `desktop/main.js`：启动后端（打包后 spawn `resources/backend/app.exe`，开发模式 spawn `python app.py`）、随机空闲端口（8767 起）、BrowserWindow 加载本地后端、自动更新（GitHub provider）、IPC（preload 桥接）。
- `desktop/preload.js`：`window.appBridge`（getVersion / checkForUpdates / downloadUpdate / installUpdate / onUpdateStatus）。
- 前端顶部新增更新区（仅 Electron 环境显示）：当前版本、检查更新按钮、下载进度条、立即更新按钮。逻辑在 `static/app.js` 的 `initUpdater()`。
- **构建命令**（在 desktop/）：
  ```powershell
  npm install
  CSC_IDENTITY_AUTO_DISCOVERY=false npx electron-builder --win nsis -c.win.signAndEditExecutable=false
  ```
- **发布新版本流程**：
  1. 改 `desktop/package.json` 的 `version`。
  2. 重新构建（如上）。
  3. 创建 release + 上传资产（用 curl 上传大文件更稳，见 0.3）。

### 0.3 自动更新（GitHub Releases）

- electron-updater，provider=github（Neko-2077/mp4-golden-clip-workbench）。
- 每次打开软件（打包版）8 秒后自动检查更新；有新版自动下载（前端进度条显示），下载完可点"立即更新"安装。
- 手动"检查更新"按钮在页面顶部。
- **坑：Windows 上中文文件名资产会导致 latest.yml 的 url 与实际资产名不匹配（自动更新 404）**。已通过 `win.artifactName: "mp4-golden-clip-workbench-setup-${version}.${ext}"` 强制 ASCII 文件名解决。
- **坑：gh release create 上传 272MB 大文件易中断**。可靠方式：先 `gh release create v1.0.x --draft=false`（不带资产），再用 curl 直传 uploads.github.com：
  ```bash
  RID=$(gh api repos/Neko-2077/mp4-golden-clip-workbench/releases --jq '.[] | select(.tag_name=="v1.0.x") | .id')
  curl -X POST -H "Authorization: token $(gh auth token)" -H "Content-Type: application/octet-stream" \
    --data-binary @"dist/mp4-golden-clip-workbench-setup-1.0.x.exe" \
    "https://uploads.github.com/repos/Neko-2077/mp4-golden-clip-workbench/releases/$RID/assets?name=mp4-golden-clip-workbench-setup-1.0.x.exe"
  ```
  blockmap 和 latest.yml 同理。不要用 `gh release upload`（会因会话中断丢资产）。
- 端到端已验证：v1.0.0 启动后自动检测 v1.0.1、自动下载 272MB 完成（`%LOCALAPPDATA%\mp4-golden-clip-workbench-updater\pending\` 出现正式文件 + update-info.json）。

### 0.4 打包后的数据目录

- PyInstaller onefile 打包后 `__file__` 指向临时解压目录，**数据必须持久化**。
- `app.py` 顶部已处理：frozen 模式下数据/配置写到 `%APPDATA%\MP4GoldenClipWorkbench`（data、user-settings.json），静态资源和 bin 从 `_MEIPASS` 读取。
- 后端打包命令（项目根目录）：
  ```powershell
  pyinstaller --noconfirm --clean --onefile --name app --add-data "static;static" --add-binary "bin/ffmpeg.exe;bin" --add-binary "bin/ffprobe.exe;bin" --collect-all tos --noconsole app.py
  ```
  产物 `dist/app.exe` 复制到 `desktop/resources/backend/app.exe`。
- ffmpeg/ffprobe 从本机 WinGet 目录拷贝到项目 `bin/`（已 gitignore）。

### 0.5 关键词搜索功能（rt32-rt37 期间新增）

- 文字稿面板下方新增"关键词搜索"区：输入词（空格分隔多词 AND）→ 搜索 → 显示 `[起点 - 终点] 句子`，关键词 `<mark>` 高亮。
- 点击结果：视频跳转到句子起点并**暂停**，手动裁切面板自动同步（开头=起点、结尾=终点），可直接微调保存。
- 前端版本已到 rt37。

## 1. 项目目标

这是一个给剪辑师使用的本地网页工作台。目标是从长 MP4/MOV 视频中筛选“金句”片段，并让用户可以预览、微调、确认、导出精华短视频。

核心使用链路：

1. 上传 MP4/MOV 原视频。
2. 前端预览原视频；如果浏览器不兼容，则生成兼容预览。
3. 转写音频为文字稿。
4. 用 DeepSeek 分析文字稿，筛出候选金句片段。
5. 为候选片段生成浏览器兼容预览。
6. 用户预览候选片段，回到原视频微调开头/结尾。
7. 用户确认片段。
8. 导出确认片段，导出必须尽量保持原始画质和原始码流。

重要原则：

- 预览可以压缩，只要不卡、能看、音频清楚。
- 最终导出必须走原视频裁切，不追求预览画质，追求导出和原视频一致。
- 前端要让用户知道任务是否在运行、进度是多少、是否失败，不能像“卡住了”。
- 不要让用户手动输入复杂时间戳，剪辑微调应尽量通过拉条、按钮、当前画面来完成。

## 2. 当前项目结构

```text
mp4-deepseek-mp4-sop/
  app.py                         # 后端主程序，HTTP API、转写、分析、剪切、导出都在这里
  requirements.txt               # Python 依赖
  start.bat                      # 启动脚本
  install-deps.bat               # 安装依赖脚本
  dependency-check.bat           # 依赖检查脚本
  user-settings.json             # 本地配置，可能保存 DeepSeek/火山/TOS 配置；不要泄露
  static/
    index.html                   # 前端页面结构
    app.js                       # 前端交互逻辑，当前版本 rt28
    app.css                      # 前端样式
  data/                          # 任务数据、上传视频、转写结果、候选片段等
  outputs/                       # 输出相关目录
  work/                          # 中间工作目录
  mp4-golden-clip-workbench-sop.md # 历史 SOP 文档
```

## 3. 运行方式

推荐使用项目根目录运行：

```powershell
cd C:\Users\Neko\Documents\Codex\2026-07-30\mp4-deepseek-mp4-sop
python app.py
```

默认监听：

```text
HOST=127.0.0.1
PORT=8767
```

也可以通过环境变量覆盖：

```powershell
$env:HOST = "127.0.0.1"
$env:PORT = "8767"
python app.py
```

依赖：

```text
opencc-python-reimplemented>=0.1.7
tos>=2.9.0
```

常用验证命令：

```powershell
python -m py_compile app.py
node --check static\app.js
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8767/
```

如果 8767 被占用，可结束监听进程后重启。注意不要误杀无关服务。

## 4. 已实现功能概览

### 4.1 上传与预览

- 支持 `MP4` 和 `MOV`。
- 前端先用浏览器 Object URL 直接预览。
- 上传到本地服务后，后端保存源文件到任务目录。
- 如果源视频编码浏览器不能直接显示画面，会生成 `browser-preview.mp4` 兼容预览。
- 兼容预览用于看画面，不用于最终导出。

关键后端函数：

- `probe_video`
- `should_make_browser_preview`
- `browser_preview_worker`
- `handle_upload`
- `handle_browser_preview`

关键前端函数：

- `needsBrowserPreview`
- `updatePreviewStatus`
- `startPolling`

### 4.2 转写

当前产品入口只保留火山引擎转写：`volcengine_bigmodel`。

历史上曾有免费本地 Whisper 转写：`local_whisper`。后端函数仍作为隐藏兜底保留，但前端入口和默认安装依赖已移除，打包时不需要默认下载 `faster-whisper` 或本地 Whisper 模型。

前端入口在 `static/index.html`：

- `transcribeEngine`：隐藏字段，固定为 `volcengine_bigmodel`
- `cloudTranscribeOptions`

后端调度函数：

```python
def transcribe_worker(job_id, task_id=None, payload=None):
    payload = payload or {}
    state = get_job_state(job_id)
    engine = payload.get("transcribe_engine") or state.get("transcribe_engine") or "volcengine_bigmodel"
    if engine == "volcengine_bigmodel":
        return volcengine_transcribe_worker(job_id, task_id, payload)
    return local_transcribe_worker(job_id, task_id)
```

本地转写历史兜底函数仍在代码中，但不是当前产品入口：

- `local_transcribe_worker`
- `resolve_transcribe_preset`

火山转写关键函数：

- `volcengine_settings`
- `tos_settings`
- `tos_upload_audio`
- `volcengine_bigmodel_request`
- `volcengine_status`
- `volcengine_extract_segments`
- `volcengine_transcribe_worker`

火山逻辑：

1. 从视频提取 `audio.wav`。
2. 如果用户没有填写公网音频 URL，则上传音频到 TOS。
3. 生成 TOS 临时 URL。
4. 调火山 BigModel ASR submit。
5. 轮询 query。
6. 转成统一 segments 格式，保存 transcript。

注意：用户只能上传视频，音频由工具台自动剥离。

### 4.3 配置保存

配置文件：`user-settings.json`

可能保存：

- DeepSeek API Key
- 火山 API Key
- 火山 Resource ID
- 火山轮询间隔
- TOS AK/SK/Endpoint/Region/Bucket/Prefix/URL 有效期

前端会读取 `/api/settings` 回填配置。火山转写开始前会自动保存当前火山/TOS 表单配置。

后端关键入口：

- `GET /api/settings`
- `POST /api/settings`
- `handle_save_settings`

安全注意：

- 不要在文档、日志、最终回复中输出真实 API Key、TOS SK。
- 如果必须显示，只显示 masked key。

### 4.4 DeepSeek 金句分析

DeepSeek 模型当前为：

```text
deepseek-v4-flash
```

后端关键函数：

- `deepseek_analyze`
- `analyze_worker`
- `handle_analyze`

当前分析策略：

- 前端传目标片段数、最短秒数、最长秒数。
- 后端会请求 DeepSeek 给出更大的候选池。
- 后端再做过滤、去重、排序、时间分布控制。
- 过滤包括置信度、分数、时长、文本相似度、时间重叠等。

注意：金句分析逻辑仍需要长期迭代。不要只依赖模型一次输出，后端过滤策略很重要。

### 4.5 候选片段预览

候选片段预览是浏览器兼容 MP4，允许重编码压缩。

关键函数：

- `clip_render_worker`
- `render_clip(export=False)`
- `pollRenderTask`
- `renderAllButton`

预览目标：

- 生成速度优先。
- 画质不必和原视频一致。
- 音频应尽量清晰，因为用户要判断句子和节奏。

### 4.6 最终导出

最终导出强调原画质，走源视频码流复制：

```text
-c copy
```

关键函数：

- `clip_export_worker`
- `render_clip(export=True)`
- `verify_stream_copy`
- `handle_export`
- `handle_pick_export_dir`

前端支持：

- 导出已确认片段。
- 单条导出。
- 用户选择导出目录。
- 清空导出目录后默认导出到任务目录 `clips/exports`。

注意：`-c copy` 在非关键帧处可能不够精确，这是视频剪切领域的常见取舍。当前需求优先保证画质一致，而不是逐帧精确。如果未来要同时保证精确和画质，需要做更复杂的 GOP/关键帧策略或智能重编码边界。

## 5. 最近重点改动

### 5.1 转写入口收敛为火山引擎

原来有本地 Whisper 版和火山引擎版两个工作台。由于火山转写速度和打包体验明显更好，当前主工作台 8767 已把前端入口收敛为火山引擎转写（BigModel ASR）。本地 Whisper 后端代码仅作为隐藏兜底保留。

火山/TOS 配置在前端填写，保存后默认回填，可修改、可清除。

### 5.2 删除环境检查面板

用户认为环境检查总显示请求失败、前端冗杂，所以环境检查面板已从页面移除。JS 里仍有少量 `refreshHealthButton/healthSummary/healthList` 残留引用，但都有空值保护，目前不影响页面。后续可清理。

### 5.3 原视频剪切微调

用户不希望输入具体时间戳，因此现在剪切区改为：

- 开头/结尾时间只读显示。
- 主拉条：拖动开头、拖动结尾。
- 精调区：选择“精调开头/精调结尾”，用局部拉条微调。
- 拖动时原视频画面会跳到对应时间。
- 删除了“开头 +/- 步长、结尾 +/- 步长”。
- 新增“拖动灵敏度”：快速定位、标准、精细、逐帧。

当前代码位置：

- HTML：`static/index.html` 中 `sourceTrimPanel`
- JS：`trimSensitivityConfig`、`syncFineSliderBounds`、`syncTrimSliderBounds`、`setFineFocus`、`setTrimValue`

注意：HTML range 的实际手感会受鼠标 DPI、屏幕宽度、浏览器缩放和视频总时长影响。对 1.5 小时视频，主拉条仍可能一拖几秒。更好的下一步是做“局部缩放时间轴”。

### 5.4 修复按钮绑定问题

曾经“重置分析参数”点了没反应，原因是 HTML 中有按钮，但 JS 元素引用表没有收进来，导致监听没有挂上。

已补齐以下按钮引用：

- `resetVideoButton`
- `resetTranscriptButton`
- `clearTranscriptViewButton`
- `resetAnalyzeButton`
- `clearClipsButton`
- `clearExportDirectoryButton`
- `refreshStorageButton`
- `cleanBrowserPreviewButton`
- `cleanClipPreviewButton`
- `cleanAudioCacheButton`
- `storageSummary`
- `storageList`
- `transcribeStats`

以后新增按钮时务必同时检查：

1. HTML 是否有 `id`。
2. JS 的 `el = { ... }` 是否引用。
3. 是否绑定事件。
4. 是否更新脚本版本号，例如 `rt28 -> rt29`。

## 6. 当前前端交互状态

页面大致分区：

1. 左侧：原视频、剪切微调、兼容预览状态、转写设置、文字稿。
2. 右侧：DeepSeek 分析、候选片段、任务中心、存储管理、历史记录。

重要按钮状态：

- 选择 MP4/MOV 后可本地预览。
- 上传到本地服务后，才可以转写、生成剪切预览、导出。
- 分析按钮需要文字稿存在后可用。
- 生成全部预览针对候选片段。
- 单条导出会弹出选择导出目录。
- 最终导出走源视频裁切。

## 7. 后端 API 概览

主要 GET：

- `/`
- `/api/settings`
- `/api/job/status?job_id=...`
- `/api/job/load?job_id=...`
- `/api/library`
- `/api/tasks`
- `/api/storage`
- `/media/<job_id>/<path>`

主要 POST：

- `/api/video/upload`
- `/api/video/browser-preview`
- `/api/transcribe/start`
- `/api/transcribe/control`
- `/api/highlights/analyze`
- `/api/clips/render-preview`
- `/api/clips/render-cancel`
- `/api/clips/manual`
- `/api/clips/update-time`
- `/api/clips/action`
- `/api/clips/export`
- `/api/dialog/export-dir`
- `/api/settings`
- `/api/storage/cleanup`

## 8. 数据文件和任务文件

每个视频上传后会有一个任务目录，通常在 `data/` 下。目录里可能包含：

- 源视频
- `metadata.json`
- `transcript.json`
- `highlights.json`
- `audio.wav`
- `browser-preview.mp4`
- `clips/preview/`
- `clips/exports/`
- 火山任务相关 JSON，例如 `volcengine_asr_task.json`、`volcengine_asr_result.json`
- TOS 上传记录，例如 `tos_audio_upload.json`

如果任务状态异常，优先查这些文件和 `/api/job/status`。

## 9. 已踩过的坑

### 9.1 浏览器只有音频没有画面

原因通常是视频编码浏览器不支持，比如某些 MOV/HEVC。解决方案是生成 H.264/AAC 的兼容预览。

注意：兼容预览生成可能很慢，前端必须显示进度、耗时、剩余估算。

### 9.2 兼容预览刷新后丢失感

如果刷新页面，前端状态会重载。后端如果已经生成 `browser-preview.mp4`，应通过历史记录或任务加载恢复。不要只存在前端内存。

### 9.3 中文问号乱码

多次发生。原因是 Windows 控制台/脚本写入编码导致中文字符串变成 `????`。

经验：

- 修改 JS 中文文案时，尽量使用 Unicode 转义，例如 `\u7cbe\u8c03`。
- HTML 可以使用实体编码，例如 `&#37329;`。
- 修改后用 `rg -n "\?\?\?|\?" static\app.js static\index.html` 检查，但注意 JS 的 `??` 是合法语法，不是乱码。
- 浏览器最终显示才是准的，PowerShell 输出不一定可靠。

### 9.4 按钮看得到但点了没反应

常见原因：

- HTML 有按钮 id。
- JS 没有 `el.xxx = $("xxx")`。
- 或者没有绑定 `addEventListener`。
- 或者脚本缓存版本没变，浏览器仍加载旧 JS。

修复后记得更新：

```html
<script src="/static/app.js?v=rt30"></script>
```

### 9.5 长视频拉条不精确

HTML range 把完整视频时长映射到控件宽度。长视频下鼠标稍微移动就会跳几秒，且与鼠标 DPI、屏幕宽度、浏览器缩放有关。

当前解决：增加“拖动灵敏度”和精调拉条。  
推荐下一步：局部缩放时间轴。

### 9.6 火山 ASR 需要公网音频 URL

火山 BigModel ASR submit 需要可访问的音频 URL。工具台现在会自动：视频 -> audio.wav -> 上传 TOS -> 临时 URL -> 火山 submit。

用户仍需填写 TOS 配置，除非将来改为后端内置或其他上传方式。

### 9.7 最终导出精度和画质冲突

`-c copy` 能保持原画质和原码流，但剪切点可能受关键帧影响。逐帧精准通常需要重编码。当前需求明确要求最终导出画质和导入视频一致，因此优先 `-c copy`。

## 10. 近期建议的开发优先级

### P0：局部缩放时间轴

当前主拉条在长视频上仍不够稳。建议下一步实现：

- 用户选择精调开头或结尾后，显示局部窗口。
- 窗口范围按灵敏度变化：例如 ±8 秒、±3 秒、±1 秒、±0.5 秒。
- 局部拉条的 min/max 不再是整条视频，而是当前点附近。
- 拖动时实时更新视频画面。
- 保留只读时间戳。

这样可以显著减少 DPI 和视频总时长对手感的影响。

### P0：彻底清理问号乱码

建议全项目检查：

```powershell
rg -n "\?\?\?|\?" static\app.js static\index.html app.py
```

人工排除 JS 合法 `??` 和 URL query `?` 后，把真实乱码全部改成 Unicode 转义或 HTML 实体。

### P1：清理旧环境检查残留

环境检查面板已删除，但 JS 里还有：

- `refreshHealth`
- `healthMessage`
- `refreshHealthButton`
- `healthSummary`
- `healthList`

它们有空值保护，不影响运行，但建议删除以减少维护噪音。

### P1：DeepSeek 金句策略继续迭代

可以改进：

- 增加“金句类型”分类，例如观点型、冲突型、故事型、方法论型、情绪型。
- 让模型返回“不推荐原因”。
- 后端加入更强的文本质量特征，例如口水话比例、抽象词密度、完整句程度。
- 对候选片段自动扩展上下文，但不要超过用户设定最大时长。
- 分析后给用户显示为什么推荐，方便人工判断。

### P1：火山配置体验简化

当前字段仍较多。可以进一步简化：

- 默认 Resource ID 为 `volc.seedasr.auc`，不突出显示。
- TOS Endpoint/Region 可按 bucket 区域提供模板。
- 增加“保存并测试 TOS 上传”按钮，但不要恢复冗杂环境检查面板。

### P2：任务恢复和并行效率

当前已有任务中心和后台任务记录。后续可以：

- 支持更多并发预览任务，但要限制 CPU 占用。
- 大任务排队时显示预计耗时。
- 页面刷新后自动恢复正在运行任务的进度。

### P2：打包准备

用户未来想打包成软件，并已有自动更新机制文档。后续打包时需要考虑：

- Python 运行时和依赖打包。
- ffmpeg/ffprobe 打包。
- 本地端口冲突处理。
- user-settings.json 的用户数据目录迁移。
- 自动更新时不要覆盖用户配置和历史任务。

## 11. 建议的接管流程

其他 AI 接手后建议按这个顺序做：

1. 先运行 `python -m py_compile app.py` 和 `node --check static\app.js`。
2. 启动 `python app.py`，打开 `http://127.0.0.1:8767/`。
3. 上传一个短 MP4 测试基本链路。
4. 测试“重置分析参数”和“拖动灵敏度”。
5. 如果修改前端，记得更新 `static/index.html` 里的 JS 版本号。
6. 如果修改中文文案，优先用 Unicode 转义或 HTML 实体防乱码。
7. 不要泄露 `user-settings.json` 中的密钥。
8. 不要破坏最终导出原画质逻辑，除非用户明确接受重编码。

## 12. 当前验证状态

最近一次已验证：

```text
python -m py_compile app.py       OK
node --check static\app.js        OK
http://127.0.0.1:8767/            200
```

当前服务已按最新代码重启过，前端脚本版本为 `rt28`。

## 13. 一句话总结

这是一个已经能跑的本地剪辑筛选工作台：上传视频、转写、DeepSeek 选金句、生成候选预览、人工微调、确认、原画质导出。接下来最值得做的是把剪切微调升级为“局部缩放时间轴”，并继续打磨金句筛选策略和火山配置体验。