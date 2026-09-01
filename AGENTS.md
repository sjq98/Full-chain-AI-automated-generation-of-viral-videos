# 发布器维护与故障记录

本文件按问题类型记录发布器、工作台网络和浏览器运行故障。运行时诊断仍写入
`data/runtime/publish-diagnostics.jsonl`，只记录时间、平台、事件和脱敏错误，
不得写入 Cookie、账号、令牌、完整表单内容或本地视频绝对路径。

## 网络与外部服务连接

### 统一网络策略

- 工作台后端和发布子进程默认使用直连。`app.py` 会清理
  `APP_PROXY`、`PUBLISHER_PROXY_SERVER`、`HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`
  及大小写变体；`urllib` 通过 `ProxyHandler({})` 建立直连。
- 发布器不读取或修改 Windows 系统代理，不传递 `--proxy-server`。不要为了绕过
  网络错误把代理地址写回应用配置或恢复旧的代理缓存。
- 本机 `127.0.0.1:7897` 等代理端口可以用于独立诊断，但不代表应用应切换到代理路由。

### GitHub Git 操作

- GitHub 相关的 Git 操作（`fetch`、`pull`、`push`、远程 workflow 操作前的仓库访问）统一使用本机代理 `http://127.0.0.1:7897`。
- 该代理规则仅适用于 GitHub 访问；工作台后端、发布器和素材/LLM 请求仍遵循上面的直连策略，不得把代理写入应用运行配置。

### `WinError 10013`：外部 TCP 连接被拒绝

- 现象：供应商测试或 B-roll 检索显示
  `外部网络连接（直连）被系统拒绝（WinError 10013）`。该错误发生在 Python
  创建到 `api.deepseek.com:443` 的 TCP socket 阶段，尚未发送 API Key、模型名或请求正文。
- 排查顺序：
  1. 用直连 `curl.exe --noproxy "*" -I --connect-timeout 10 --max-time 20 https://api.deepseek.com/models`
     复现。
  2. 用同一个 Python 解释器执行
     `socket.create_connection(("api.deepseek.com", 443), 10)`，记录 `winerror`。
  3. 对比 `netsh winhttp show proxy`、`netsh advfirewall show allprofiles`、
     `Test-NetConnection 127.0.0.1 -Port 7897`，确认 WinHTTP、Windows 防火墙、WFP
     或安全软件状态。必要时在系统级权限下重复探针，避免把受限运行环境误判为本机网络故障。
- 判定：
  - 受限终端中的 Python 和 `curl --noproxy` 都失败，而系统级 Python/curl 成功，
    说明是受限运行环境的出站权限，不是 DeepSeek、API Key 或应用路由问题。
  - 系统级直连能返回 HTTP 401/403，说明 TCP 和 TLS 已连通，应检查 API Key、模型或
    服务端权限，不要继续修改代理。
  - 系统级直连也返回 10013，才检查 Windows 防火墙出站策略、WFP、安全软件、VPN
    或网络设备的拦截。
- 本次恢复：曾发现通过受限 Codex 终端启动的 Python 进程触发 10013；授权探针确认
  `api.deepseek.com:443` 可直连并返回 401，`Python 3.12.10` 的 socket 连接成功。
  停止受限进程后，使用
  `C:\Users\shaoj\AppData\Local\Programs\Python\Python312\python.exe`
  重启工作台，`POST /api/providers/llm-test` 对已启用 DeepSeek 配置返回 HTTP 200。
- 正常启动入口：运行项目目录中的 `start.bat`，不要从受限 Codex 终端直接把
  `app.py` 作为长期服务启动。启动后确认 `127.0.0.1:8789` 只有一个监听进程。

### 代理连接失败或网络被拒绝

- 发布页面出现 `ERR_PROXY_CONNECTION_FAILED` 或 `ERR_NETWORK_ACCESS_DENIED` 时，
  清除发布子进程中的代理环境变量和 Chrome 的代理参数；发布器使用 Google Chrome
  直接启动。
- 若直连和代理都失败，先记录 DNS、TCP、WinHTTP、防火墙和安全软件结果，再处理网络
  环境；不要在应用层猜测代理地址。

## macOS 打包与运行

### 已打包应用的 TLS 证书校验失败

- 现象：macOS DMG 内的应用请求 DeepSeek 等 HTTPS 服务时显示
  `SSL: CERTIFICATE_VERIFY_FAILED`、`self-signed certificate in certificate chain`，而源代码模式下请求正常。
- 原因：PyInstaller 产物不能稳定发现 Python 系统信任根或 `certifi` 的 PEM 数据；源代码环境与冻结后的
  可执行文件所见的证书路径不同。
- 处理：`app.py` 的公共 HTTP opener 使用验证模式的 SSL context，同时加载系统默认信任根与
  `certifi.where()`；发布构建把 `certifi` 列为显式依赖，并用 PyInstaller 的
  `--collect-all certifi` 复制证书数据。不要为绕过错误关闭 TLS 校验，也不要把代理证书当作常规方案。
- 验证：在 macOS 已安装的 DMG 中执行供应商连接测试，并确认请求没有
  `CERTIFICATE_VERIFY_FAILED`；Windows 或源码模式的成功不能替代该验证。

### 转写后“分析金句片段”显示 `fail to fetch`

- 现象：macOS 应用完成文字稿转写后，点击分析金句片段，界面仅显示 `分析失败：fail to fetch`。
- 原因：前端轮询分析任务时，某些网络/服务端非 JSON 响应直接传播了浏览器原始 `fetch` 异常，
  没有转换为可诊断的应用错误。
- 处理：分析任务的前端请求统一解析 HTTP 状态和响应正文，并在轮询、取消或读取任务状态失败时
  保留服务端的错误信息；后端继续使用统一的 LLM 请求路径。
- 验证：在 macOS DMG 中完成一次转写并启动分析，确认失败时显示具体 HTTP/服务端信息，
  成功时状态可从排队、分析中更新到完成。

### DeepSeek 未返回可解析 JSON

- 现象：分析任务显示 `我的ds未返回可解析的内容：模型返回内容中没有可解析的JSON对象`。
- 原因：OpenAI 兼容接口可能把最终 `content` 留空，或在推理模式下没有产出符合工作台契约的 JSON；
  此前请求也没有把调用方的 `max_tokens` 实际传给接口。
- 处理：识别 DeepSeek 直连和兼容网关后，在 OpenAI 请求中发送 `max_tokens`、
  `response_format: {type: json_object}` 与 `thinking: {type: disabled}`。若首次最终内容为空或
  不能解析，使用明确的 JSON 输出指令重试一次；仍失败时保留解析错误，不把原始响应伪装为成功。
- 验证：覆盖 JSON 模式参数、token 预算和“首次空内容、第二次有效 JSON”的回归测试；发布 DMG 后
  使用真实 DeepSeek 供应商完成一次金句分析。

### Apple Silicon DMG 与本地后端架构不匹配

- 现象：在非 macOS 主机打包，或把 Intel 构建的后端混入 Apple Silicon DMG 时，应用无法运行、
  后端启动失败或出现架构不匹配。
- 原因：应用内的 Python/PyInstaller 后端、FFmpeg 和 Electron 原生组件都依赖构建主机架构，
  Windows 不能产出可验证的 macOS 后端。
- 处理：仅在 GitHub 的 `macos-15` Apple Silicon runner 上构建；
  `desktop/scripts/package-macos.js` 对后端 manifest 的 `darwin/arm64`、可执行文件和
  `app.py` 哈希做打包前校验。自动和手动 macOS workflow 均只保留 `arm64` 矩阵，
  产物名为 `mp4-golden-clip-workbench-macos-arm64`。
- 验证：Actions 中只有一个 `macOS arm64` job，且 artifact 内包含 DMG；在 Apple Silicon Mac
  上启动后确认后端就绪并能执行一次供应商连接测试。

### DMG 交付与 Gatekeeper 提示

- 现象：未签名、未公证的本地 DMG 首次打开时，macOS 可能提示开发者无法验证或阻止启动。
- 原因：当前发布工作流没有配置 Apple Developer 签名证书和 notarization 凭据。
- 处理：交付时明确该 DMG 是 Apple Silicon (`arm64`) 构建；在受信任来源确认后，由用户在
  Finder 中按住 Control 点击应用并选择“打开”，或在“隐私与安全性”中显式允许。不得通过关闭
  Gatekeeper 或修改系统级安全策略来规避。
- 验证：在干净的 Apple Silicon macOS 账户中完成挂载、拖拽安装、首次授权和启动；若要消除
  提示，后续必须配置 Developer ID 签名与 Apple notarization，而非仅重打包。

## 浏览器启动、Playwright 与窗口生命周期

### 共享 CDP、黑屏和空白页

- 共享 CDP、独立 profile、调试端口或会话文件残留会造成黑屏 Chrome、额外
  `about:blank`、没有可见窗口或后台状态与真实窗口不一致。
- 抖音和视频号使用各自上游的直接 Playwright 启动模型：`headless=False`、
  `executable_path` 指向本机 Google Chrome、一个浏览器和一个页面；不再通过共享
  CDP 启动或连接发布窗口。

### 单窗口与并发稳定性

- 当前 Windows/Chrome/Playwright 组合在多个驱动同时 `Browser.new_context` 时可能
  报 `Connection closed while reading from the driver` 或 Node `Assertion error`。
- 发布任务和登录准备保持全局锁串行：同一时间只初始化一个发布器；关闭或完成当前
  窗口后再继续下一个平台。不要通过并行或错峰启动规避。
- 每个平台上下文优先复用同平台页面或初始空白页，关闭多余标签，确保最终只有一个
  发布页。

### Chrome 启动参数、窗口可见性与登录态

- 只使用 Google Chrome，不回退到 Edge 或 Playwright 默认 Chromium。
- 过滤 Playwright 自动注入的 `--no-sandbox`、`--enable-unsafe-swiftshader` 及 GPU
  绕过参数；不设置 `--proxy-server`、`--disable-gpu` 等代理或 GPU 绕过参数。
- 页面创建和导航后，通过当前页面对应的 DevTools `windowId` 将窗口恢复为普通状态，
  移动到可见区域 `(60, 40)`；不要只依赖 `bring_to_front` 或 `--start-maximized`。
- 本机 Chrome 151 与 Playwright 1.62 对旧的完整 `storage_state` 导入可能导致驱动
  崩溃。发布和登录只从登录态 JSON 导入 Cookie，不传递完整 `storage_state`；登录失效
  时重新执行“登录准备”。

### 用户关闭窗口

- 用户在自动化等待期间关闭 Chrome 或页面时，识别 `TargetClosedError` 和
  `PUBLISHER_USER_CLOSED_WINDOW`，任务显示“用户已关闭发布窗口，任务已停止，未发布”，
  不显示 Python/Playwright 堆栈。
- 窗口关闭后允许再次创建登录或发布任务，不复用已失效的浏览器状态。

## 发布任务状态与人工确认

### 人工确认记录阻塞重试

- `status=succeeded` 且 `result_state=awaiting_manual_confirmation` 的历史记录不代表
  当前仍有窗口，不能阻塞新任务。
- 只有 `planned`、`queued`、`running` 视为活动发布任务；完成、失败或取消的记录允许
  再次发布。直接启动模型没有可查询的共享浏览器会话，不要用历史记录推断窗口仍存在。

### 多平台发布

- 一键发布表单按抖音、视频号、小红书分别维护参数。视频号单独传递视频描述、短标题
  和标签；抖音、小红书不复用视频号字段。
- 多平台任务按单窗口串行执行，当前平台完成或窗口关闭后自动继续下一个平台。

## 上游仓库与本地集成

- 核对对象：`DaBaoAgent/douyin-auto-publish`、`frankwei2019/auto-weixin-video`、
  `ShunL12324/xhs-mcp`。本地三个 vendor 仓库的 `origin` 指向对应地址；更新前使用
  `git fetch --dry-run origin` 检查。
- 本地集成允许保留必要改动：应用任务参数、Google Chrome 路径、无代理子进程环境、
  Cookie-only 登录态恢复，以及小红书的窗口复用和启动参数适配。不能声称 vendor 源码
  是未经修改的原样副本。
- 已验证的发布稳定性基线：Python 编译通过；小红书 TypeScript 构建通过；发布回归
  测试通过；真实 Chrome 访问抖音创作者中心返回 HTTP 200；专用上下文只有一个页面；
  启动日志没有代理、沙箱或 GPU 绕过参数。

## 维护规则

- 新故障按“现象、原因、处理、验证”四项补充到对应问题类型，不再按日期重复建立
  条目；同一根因的记录应合并维护。
- 运行时诊断只写时间、平台、事件和脱敏错误，不写 Cookie、账号、令牌、完整表单内容
  或本地视频绝对路径。
- 修改发布启动模型、代理策略、并发锁或登录态导入方式后，必须重新运行对应回归测试，
  并确认没有残留旧进程占用 `127.0.0.1:8789` 或小红书服务端口 `18060`。
