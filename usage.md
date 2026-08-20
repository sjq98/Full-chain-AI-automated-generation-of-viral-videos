# MP4 Golden Clip Workbench 使用说明

本项目可作为本地源码包在 Windows 和 macOS 上运行。源码包不需要安装已签名的 DMG 或 EXE，但首次使用需要在本机安装依赖。

## 发送源码包前

建议通过 GitHub 的 **Code > Download ZIP** 下载源码，或使用 Git 生成干净压缩包：

```bash
git archive --format=zip --output MP4-Golden-Clip-Workbench-source.zip main
```

不要发送以下本地文件或目录：`data/`、`browser_data/`、`user-settings.json`、`.logs/`、`vendor/MediaCrawler/.venv/`、`.git/`、`desktop/node_modules/`。其中可能包含个人配置、任务和视频历史、平台登录状态或当前电脑专用的依赖文件。

## Windows 使用方法

### 首次安装

1. 将源码 ZIP 解压到可写入目录，例如“文档”。
2. 安装 Python 3.10、3.11 或 3.12；安装时勾选 **Add Python to PATH**。
3. 安装 FFmpeg，并确认命令行能找到 `ffmpeg` 和 `ffprobe`。可使用：`winget install Gyan.FFmpeg`。
4. 双击运行 `install-deps.bat`，等待依赖安装完成。
5. 双击运行 `start.bat`。

工作台会在浏览器中打开：`http://127.0.0.1:8789/`。使用期间请保持命令提示符窗口开启；关闭该窗口会停止本地服务。

### 依赖检查失败时

在项目目录打开命令提示符，执行：

```bat
python --version
ffmpeg -version
ffprobe -version
```

修复缺失项后，再次运行 `install-deps.bat`。

## macOS 使用方法

### 首次安装

1. 将源码 ZIP 解压到可写入目录，例如“文稿”。
2. 如未安装 Homebrew，请先前往 [Homebrew 官网](https://brew.sh) 安装。
3. 在 Finder 中右键 `macos-install.command`，选择“打开”。脚本会安装 Python 3.11、FFmpeg、MediaCrawler 依赖、yt-dlp 和 Playwright Chromium。
4. 安装完成后，右键 `macos-start.command`，选择“打开”。

启动后会在默认浏览器打开 `http://127.0.0.1:8789/`。使用期间请保持脚本启动的终端窗口开启。运行日志位于 `.logs/workbench.log`。

### macOS 阻止运行脚本时

打开“终端”，进入解压后的项目目录后执行：

```bash
chmod +x macos-install.command macos-start.command
./macos-install.command
./macos-start.command
```

## 首次配置

1. 在工作台中打开“供应商管理”。
2. 配置需要使用的转写供应商和大模型供应商。
3. 上传本地 MP4/MOV 视频，或进入“爆款搜索”查找视频并导入工作台。

供应商配置、任务记录和视频文件只保存在当前用户的电脑上，不会被包含在干净源码包内。

## 爆款搜索的平台登录

首次使用 MediaCrawler 平台搜索时，项目会打开自己的 Chrome 会话。请在该浏览器窗口中登录所需平台一次。登录状态会本地保存到 `browser_data/`，之后搜索会自动复用。

不要分享 `browser_data/`，其中可能包含平台登录 Cookie。请仅将该功能用于个人、合法的研究用途，并遵守各平台规则与适用法律。

## 停止工作台

- Windows：关闭由 `start.bat` 打开的命令提示符窗口。
- macOS：关闭由 `macos-start.command` 打开的终端窗口，或在窗口中按 `Control + C`。

工作台只监听本机地址，不会向公网开放端口。
