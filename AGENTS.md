# 发布器维护与故障记录

本文件是发布器的唯一故障排查记录。运行时诊断仍写入
`data/runtime/publish-diagnostics.jsonl`，只记录时间、平台、事件和脱敏错误，
不得写入 Cookie、账号、令牌、完整表单内容或本地视频绝对路径。

## 2026-08-24：代理连接失败或网络被拒绝

- 现象：抖音页面出现 `ERR_PROXY_CONNECTION_FAILED` 或 `ERR_NETWORK_ACCESS_DENIED`。
- 原因：旧版发布器读取了 `APP_PROXY`、`PUBLISHER_PROXY_SERVER`，或独立浏览器 profile 中残留代理状态。
- 处理：发布子进程清除代理环境变量，不传递 `--proxy-server`；发布器按上游项目直接启动本机 Google Chrome。
- 验证：启动命令中没有代理参数，Chrome 使用 Windows 当前网络配置。

## 2026-08-24：用户关闭窗口出现 Playwright 堆栈

- 现象：任务记录显示 `TargetClosedError`。
- 原因：用户在自动化等待期间手动关闭了页面或浏览器。
- 处理：识别 `TargetClosedError` 和 `PUBLISHER_USER_CLOSED_WINDOW`，发布任务显示“用户已关闭发布窗口，任务已停止，未发布”，登录任务显示“用户已关闭登录窗口，登录准备已停止”。
- 验证：关闭抖音或视频号窗口后，任务状态为已取消，不显示 Python/Playwright 堆栈。

## 2026-08-25：共享 CDP 会话导致黑屏、空白页或没有窗口

- 现象：点击发布后出现黑屏 Chrome、额外 `about:blank`，或后台没有可见窗口。
- 原因：共享 CDP 层需要独立 profile、调试端口和会话文件；Chrome 退出、PID 交接或 profile 锁残留后，后台状态与真实窗口不一致。
- 处理：抖音和视频号恢复各自上游项目的直接 Playwright 启动模型：`headless=False`、`executable_path` 指向 Google Chrome、一个浏览器和一个页面；不再通过 CDP 启动或连接发布窗口。
- 验证：点击发布后只启动 Google Chrome，目标平台只打开一个发布页面，不创建额外空白标签。

## 2026-08-25：手动审核记录阻塞重试

- 现象：关闭人工审核窗口后，任务仍显示等待手动发布，下一次相同成片无法重新打开。
- 原因：旧逻辑依赖共享 CDP 页面探测，直接启动模型没有可复用的共享端点。
- 处理：直接启动的发布器在窗口关闭时返回关闭标记；后端把任务置为“用户已关闭发布窗口”，允许重新创建任务。
- 验证：关闭窗口后再次点击发布，可以重新启动一个新的 Google Chrome 发布窗口。

## 2026-08-25：旧后端仍占用发布接口端口

- 现象：源码已经改为 Chrome 直接启动，但界面能力接口仍返回 `chrome_cdp`，点击后继续表现为旧逻辑。
- 原因：Windows 上残留的多个旧 `app.py` 实例同时监听 `127.0.0.1:8789`，请求可能落到未更新的实例。
- 处理：停止占用 `8789` 和旧小红书服务端口 `18060` 的残留项目进程，只启动当前源码对应的一套后端与按需的小红书服务。
- 验证：`/api/publish/capabilities` 中抖音和视频号均返回 `execution_mode: chrome_direct`，标签为“Google Chrome 直接启动”。

## 2026-08-25：多平台发布页被全局浏览器锁串行阻塞

- 现象：同时勾选抖音、视频号或小红书时，只先打开一个平台；必须关闭前一个窗口后，后一个平台才出现。
- 原因：发布任务虽然分别在线程中执行，但 `publish_task_worker()` 仍使用 `PUBLISH_BROWSER_LOCK` 包住整个发布器进程。人工审核模式会保持浏览器，因此后续任务一直等待。
- 处理：曾尝试移除发布锁以并行打开多个平台窗口，但当前 Windows/Chrome/Playwright 组合会在同时创建上下文时让两个驱动断开。因此恢复为原来的串行发布：每次只启动一个发布器，关闭或完成当前窗口后自动继续下一个平台。登录准备同样保持锁，避免登录态被同时写入。
- 另外：一键发布表单拆成抖音、视频号、小红书三个独立参数区。视频号分别传递视频描述、短标题和标签，抖音/小红书不再复用视频号字段。
- 验证：同时选择多个平台时，第二个平台在第一个窗口关闭或任务结束前不会初始化 Chrome；视频号命令包含 `--short-title`，小红书仍强制使用自动发布模式。

## 2026-08-25：多个 Playwright Chrome 驱动同时创建上下文

- 现象：抖音和视频号在同一秒点击一键发布后，都在 `Browser.new_context` 报 `Connection closed while reading from the driver`；驱动日志同时出现 Node `Assertion error`。
- 原因：当前 Windows/Chrome/Playwright 运行组合在两个独立 Chrome 驱动同时初始化上下文时不稳定。单平台历史记录可正常完成上传和填表，故不是发布字段或网络代理导致。
- 处理：不再并行或错峰启动两个 Playwright 发布器，恢复为经过验证的单窗口串行路径；不对该类异常自动重试，避免在浏览器状态不明时重复执行发布器。
- 验证：同一时间只有一个发布器进入 `Browser.new_context`，并沿用此前稳定的单平台 Chrome 直连路径。

## 2026-08-25：旧登录态的完整 storage_state 导入导致 Chrome 驱动崩溃

- 现象：即使只启动单个平台，抖音或视频号在 `Browser.new_context(storage_state=...)` 报 `Connection closed while reading from the driver`；Playwright Node 驱动随后报 `Assertion error`。
- 原因：本机 Chrome 151 与 Playwright 1.62 可以正常创建普通可见上下文。最小复现表明，只有把旧登录态 JSON 作为完整 `storage_state` 导入时崩溃；该 JSON 中的 localStorage/origins 导入与当前 Chrome 驱动不兼容。
- 处理：恢复普通 Google Chrome 直接启动和单页上下文；不再传递 `storage_state`，只从原登录态 JSON 导入 Cookie。Cookie 导入已单独验证可以成功创建上下文，不设置代理、`--no-sandbox` 或 GPU 绕过参数。
- 验证：普通 `launch + new_context` 成功；导入完整 storage state 复现崩溃；导入相同文件中的 Cookie 后成功创建上下文。若平台提示登录失效，重新执行“登录准备”保存新的 Cookie 即可。

## 2026-08-25：发布窗口没有出现，恢复上游启动形态

- 现象：叠加 `ignore_default_args`、最大化和窗口位置修补后，点击一键发布或登录准备仍可能没有可见发布页。
- 原因：这些本地启动补丁偏离了上游 `launch -> new_context -> new_page -> goto` 形态，且不同平台保留了不一致的启动参数，难以确认实际 Chrome 启动状态。
- 处理：抖音与视频号恢复上游的最小启动参数：`headless=False` 和 `--disable-blink-features=AutomationControlled`。仅保留 `executable_path` 指向 Google Chrome、发布子进程清除代理环境变量，以及 Cookie-only 登录态导入；后者避免旧完整 `storage_state` 在本机 Chrome/Playwright 组合中触发驱动崩溃。
- 验证：在发布器实际使用的 Python 和 `C:\Program Files\Google\Chrome\Application\chrome.exe` 上，最小路径 `launch -> new_context -> new_page` 已成功运行。

## 2026-08-25：已结束的人工确认记录错误阻止重新发布

- 现象：界面提示“该成片的抖音发布页已在准备或等待人工确认”，但没有可见 Chrome 窗口，新的发布任务无法创建。
- 原因：任务去重逻辑将 `status=succeeded` 且 `result_state=awaiting_manual_confirmation` 的历史记录也视为活动任务。直接启动的发布器没有可查询的共享浏览器会话，因此这个历史状态不能证明窗口仍存在。
- 处理：只将 `planned`、`queued`、`running` 视为活动发布任务；完成、失败或取消的记录不再阻塞再次发布。清理本次遗留的无窗口发布驱动进程后重启后端。
- 验证：重启后的 `/api/publish/tasks` 没有活动或人工确认占位任务；回归测试覆盖“完成的人工确认记录仍可重新创建发布任务”。

## 上游仓库核对（2026-08-25）

- 核对对象：`DaBaoAgent/douyin-auto-publish`、`frankwei2019/auto-weixin-video`、`ShunL12324/xhs-mcp`。
- 本地三个 vendor 仓库的 `origin` 均指向以上地址，且 `git fetch --dry-run origin` 未发现待更新提交。
- 注意：发布工作台仍保留少量必要集成改动，例如应用自己的任务参数、Google Chrome 路径、无代理子进程环境和 Cookie-only 登录态恢复；不能声称这三份 vendor 源码是未经修改的原样副本。

## 2026-08-25：统一单窗口 Chrome 启动策略

- 现象：三个平台的启动参数和页面选择方式不一致；Playwright 会自动加入 `--no-sandbox` 和 SwiftShader 兼容参数，持久化上下文也可能已有空白页。仅调用 `bring_to_front` 或使用 `--start-maximized` 不能可靠恢复最小化、屏外窗口，并可能留下重复标签。
- 原因：上游发布器分别维护浏览器生命周期，本地集成此前只统一了 Chrome 可执行文件，没有统一过滤 Playwright 默认参数、复用现有页面和恢复当前窗口边界。
- 处理：抖音、视频号和小红书均只指定本机 Google Chrome；启动参数不设置代理，并通过 `ignore_default_args` / `ignoreDefaultArgs` 过滤 `--no-sandbox`、`--enable-unsafe-swiftshader` 及其他 GPU 绕过参数。每个发布器专用上下文优先复用同平台页或初始空白页，关闭其余标签；页面创建和导航后通过 DevTools `Browser.setWindowBounds` 将当前 Chrome 窗口恢复为普通状态并移动到 `(60, 40)` 的可见区域。
- 验证：Python 编译、小红书 TypeScript 构建及 35 项发布回归测试通过。真实 Google Chrome 访问 `https://creator.douyin.com/` 返回 HTTP 200，专用上下文只有 1 个页面，窗口恢复返回成功；Playwright 实际启动日志中没有 `--proxy-server`、`--no-sandbox`、`--disable-gpu` 或 `--enable-unsafe-swiftshader`。

## 本次修改范围总结

- `vendor/publishers/chrome_runtime.py`：新增 Python 公共浏览器策略。统一 Google Chrome 启动参数、过滤 Playwright 自动注入的沙箱/GPU 绕过参数、复用已有平台页或空白页、关闭多余标签，并通过当前页面对应的 DevTools windowId 恢复最小化和屏外窗口。它只调整当前发布页面的窗口，不负责共享 Chrome/CDP 启动。
- `vendor/publishers/douyin-auto-publish/scripts/dy_video_publish.py`：抖音发布流程改用公共策略，启动后只保留一个发布页，并在导航后再次恢复窗口可见性。
- `vendor/publishers/auto-weixin-video/scripts/publish.py`：视频号发布流程改用同一套单页、单窗口和 Chrome 参数策略。
- `vendor/publishers/auto-weixin-video/scripts/get_cookie.py`：视频号登录准备也统一为单窗口，复用初始页面并清理多余标签。
- `app.py`：抖音登录准备接入同一套 Chrome 启动和窗口恢复逻辑；平台任务仍保持串行，避免多个 Playwright 驱动同时创建上下文。
- `vendor/publishers/xhs-mcp/src/xhs/clients/browser-window.ts`：新增小红书 TypeScript 窗口/页面复用工具；`constants.ts` 统一窗口尺寸和默认参数过滤；登录、上下文初始化、视频/图文发布入口全部接入。构建后同步更新 `dist/`。
- `tests/test_publish_flow.py`：新增启动参数、页面复用、重复标签清理、窗口边界恢复和小红书启动策略回归测试。
- 验证结果：Python 编译通过；小红书 `npm run build` 通过；发布相关回归测试共 36 项全部通过；真实 Chrome 访问抖音创作者中心返回 HTTP 200、上下文页面数为 1、窗口恢复成功；启动日志未出现代理、`--no-sandbox` 或 GPU/SwiftShader 绕过参数。

## 维护规则

- 只使用 Google Chrome；不回退到 Edge 或 Playwright 默认 Chromium。
- 发布器不设置代理，不传递 `--proxy-server`；Chrome 启动形态以对应上游项目为准，除非有可复现且经验证的兼容性问题。
- 发布页面的浏览器生命周期由对应上游发布脚本负责；不要重新加入共享 CDP 启动层。
- 新故障补充“现象、原因、处理、验证”四项，并同步运行时脱敏诊断。

## 2026-08-26：DeepSeek 直连恢复记录

- 现象：供应商管理中的 DeepSeek 连通性测试曾返回 `WinError 10013`，错误发生在 Python 对 `api.deepseek.com:443` 建立 TCP 连接之前，尚未发送 API Key、模型或请求正文。
- 已排除：这不是供应商列表、模型 ID、`--no-sandbox`、GPU 绕过参数或 Playwright/Chrome 引起的。后四者只影响浏览器启动，不能改变 Python 的 HTTPS socket 权限。
- 应用网络约束：后端会清理 `HTTP_PROXY`、`HTTPS_PROXY`、`ALL_PROXY`、`APP_PROXY` 和 `PUBLISHER_PROXY_SERVER`；`urllib` 通过 `ProxyHandler({})` 发起直连。不要为解决此问题在应用内写入代理地址，也不要恢复旧的代理缓存。
- 恢复后的验证：2026-08-26，已启用的 `deepseek-v4-flash` 配置通过 `POST /api/providers/llm-test` 返回 HTTP 200，耗时约 1.1 秒；供应商 URL 为 `https://api.deepseek.com`。未在日志或配置中记录 API Key。
- 维护结论：若再次出现 `WinError 10013`，先用相同的供应商连通性测试和 `curl.exe --noproxy "*" https://api.deepseek.com/models` 复现；若二者都失败，应检查 Windows/安全软件/网络的出站阻断，而不是修改模型字段或浏览器启动参数。服务恢复后保留直连实现，不新增应用代理。
