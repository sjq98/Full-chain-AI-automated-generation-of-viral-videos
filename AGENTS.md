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
