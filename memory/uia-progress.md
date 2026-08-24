# UIA 发送与消息日志改造进度

## 记录时间

2026-08-24

## 总体目标

在 Windows 11 + 微信 4.1.12.26 环境下，使用 UI Automation（UIA）实现不移动鼠标、不开启坐标点击的微信消息发送，并补齐以下能力：

- 支持私聊和群聊发送。
- 正确识别群聊名称、群成员名称和成员 ID。
- 支持多微信账号绑定、选择和状态识别。
- 对每条入站和出站消息记录方向、状态、失败原因和关联关系。
- 在管理界面提供发送诊断、重启和日志查看能力。

## 当前结论

UIA 的基础可用性已经确认：微信窗口的 UIA accessibility gate 可以被热激活，发送流程已经接入 UIA 同步执行入口，会返回分阶段结果；发送后支持 UI、数据库和 pending 查库确认。真实机器上的只读 UIA、搜索切换和正文回读已经验证。

前台 UIA 的按钮 Pattern 在当前微信版本上会返回调用成功但不清空草稿；后台 `InvokePattern` 会把窗口切到前台，已被保护逻辑拦截；后台 `LegacyIAccessible.DoDefaultAction` 不抢前台但不发送。当前 `auto` 路径优先尝试 `background_uia + PostMessage:WM_LBUTTON`，能力不足或目标不可见时可按配置切换 `foreground_uia`；如果后台动作改变前台输入状态，则立即熔断，不再切换路径重发。后台实机验证确认 PostMessage 可以发送：草稿清空、数据库产生本人消息、前台窗口/键盘焦点/鼠标坐标保持不变。数据库时间戳偶尔早于发送调用返回约 1 秒，已增加 3 秒回读容错。

管理界面现在可以执行只读 UIA 检测，返回选中账号、绑定 PID、窗口句柄、当前会话、搜索框、聊天输入框和发送按钮的 Pattern 信息。检测不会发送消息，也不会主动移动鼠标。

发送链路已经完成测试账号的后台闭环；仍需在微信升级或窗口结构变化后重新执行诊断与回归。

## 已完成

以下项目已经完成调查、代码确认或环境确认：

- [x] 确认项目当前使用 `wechatauto-replica 1.1.7`。
- [x] 确认项目当前使用 `uiautomation 2.0.29`。
- [x] 确认 UIA accessibility gate 可以热激活。
- [x] 确认当前配置为 `method: uia`。
- [x] 确认当前默认配置为 `send_mode: auto`，优先后台 UIA，条件不足时按配置切换前台 UIA。
- [x] 确认当前配置为 `allow_mouse_fallback: false`。
- [x] 确认 UIA 运行时要求 Python 3.12 x64，并拒绝 32 位 Python。
- [x] 确认 `sender_windows_uia.py` 中已经存在 `_find_send_button()`。
- [x] 确认当前前台 UIA 路径不再默认使用 `SendKeys("{Enter}")`，按键仅作为显式配置的兜底。
- [x] 确认群聊数据库记录包含 `real_sender_id` 字段，并已接入 `Name2Id.rowid -> user_name` 映射。
- [x] 确认群聊解析失败时仍需要保留可诊断的 fallback，不能把 fallback 当作真实成员名称。
- [x] 确认旧版群消息正文可能包含 `wxid_xxx:\n` 形式的发送者前缀，并已加入清理逻辑。
- [x] `messages` 表已增加入站/出站方向、发送状态、尝试 ID、关联消息、错误阶段和数据库验证字段。
- [x] 消息日志 API 会修复历史群聊记录中的发送者前缀和“群 ID 冒充发送者”问题；前端分别展示群名、成员 ID、回复关联和出站失败阶段。
- [x] 确认已有 SQLite 数据库不能仅依赖 `create_all()` 自动增加新字段。
- [x] 确认 Python 3.12 虚拟环境位于 `D:\Wechat_bot\weix\venv`。
- [x] 确认 Python 3.13 环境调用 `_prepare_windows_imports()` 后可以找到 `win32ui`，问题重点在启动环境和导入路径。
- [x] 完成 UIA 结构化 `SendResult`，可以区分窗口、搜索、正文、调用和 UI 验证阶段。
- [x] UIA 发送优先查找真实“发送”按钮，并调用 `InvokePattern` / `LegacyIAccessible.DoDefaultAction`。
- [x] 修复 UIA 结构化发送结果调用了缺失同步入口的问题；现在 `foreground_uia`、`background_uia` 和 `auto` 都会进入统一的 UIA 执行器。
- [x] 增加输入框写入后的 ValuePattern 回读校验。
- [x] 增加 UIA 控件诊断方法，返回账号、PID、窗口、搜索框、输入框、发送按钮和 Pattern 信息。
- [x] 前台 UIA 在窗口过窄时通过 Win32 `ShowWindow(SW_MAXIMIZE)` 恢复搜索框和会话列表，不移动鼠标、不使用坐标点击。
- [x] 搜索结果和可见会话遇到同名候选时返回 `ambiguous_search_result`，打开会话后同时校验标题和 `chat_input_field`。
- [x] 增加 `GET /api/platform/uia/diagnose` 诊断接口，并在聊天配置页增加“UIA 检测”按钮和结果弹窗。
- [x] 修复 UIA 诊断窗口 PID 获取：优先使用 UIA 驱动能力，必要时使用 Win32 `GetWindowThreadProcessId`，避免调用不存在的发送器方法。
- [x] 管理界面提供后端重启按钮，账号切换后可以重新绑定数据库、监听器和微信窗口。
- [x] 启动脚本改为固定使用 `venv\Scripts\python.exe`，并在启动前检查 UIA 依赖是否来自同一环境。
- [x] 从外部 Python 3.13 的 `_pth` 中移除 `venv-py313-stale` 路径。
- [x] `auto` 在后台能力可用时保留前台 UIA 候选，但仅在没有执行发送动作且没有触发输入状态变化时允许切换。
- [x] 前台 Pattern 假成功时尝试 UIA 发现的按钮 `PostMessage:WM_LBUTTON`，不移动真实鼠标。

## 尚未完成

以下项目仍未完成或尚未得到真实运行验证：

- [x] 增加数据库验证，按 `target_id` 和正文哈希确认发送成功消息已经写入本地消息记录；未及时落盘时进入 `pending_verify`，后台只查库，不重复发送；允许 3 秒数据库时间戳偏差。
- [x] 增加多账号选择、选中账号/绑定账号/PID 绑定和在线状态返回；多进程未选账号时启动会拒绝猜测。
- [x] 在测试账号上完成前台 UIA、后台 `InvokePattern` 和后台 `LegacyIAccessible.DoDefaultAction` 的隔离测试，并确认后台 `PostMessage:WM_LBUTTON` 实际发出消息。
- [x] 完成测试账号私聊后台发送验证，并取得 UI、数据库和前台输入设备不变的闭环证据。
- [ ] 完成测试账号群聊发送验证，并取得群成员可见的闭环证据。
- [x] 将数据库回读的本人消息合并到对应出站日志，避免同一条消息同时显示“发出”和“收到”。
- [x] 通过单元测试验证多开微信时，UIA 诊断和发送器拒绝未知 PID、账号不匹配和窗口 PID 不一致。
- [ ] 验证发送失败、窗口关闭、会话切换和微信升级后的错误阶段与恢复行为。

## 技术实施顺序

1. 固定后端启动解释器和依赖环境。
2. 完成 UIA 控件探测与结构化发送结果。
3. 实现发送按钮 `InvokePattern` / `DoDefaultAction`。
4. 增加发送后的 UI 和数据库双重验证；数据库延迟时由后台 pending 查库任务收敛状态。
5. 修复群聊发送者、正文和消息方向模型。
6. 增加迁移、API、前端日志和管理操作。
7. 通过本地测试后，再进行用户确认的真实消息测试。

## 验收标准

- 不移动鼠标、不依赖坐标点击时，私聊文本可以稳定发送。
- 微信设置为 Enter 或 Ctrl+Enter 时，发送策略都能按配置工作。
- 群聊日志能显示真实群名称、真实发送者名称和正确正文。
- 入站和出站消息都能在日志中区分方向。
- 发送失败时能看到明确失败阶段和原因，而不是只有“发送失败”。
- 发送成功必须同时具备 UI 验证和数据库记录，不能只依赖函数没有抛异常。
- 重启后配置、账号状态和日志仍能正确恢复。

## UIA 技术验收要点

### 账号和进程绑定

发送器不会在多个微信进程中猜窗口。账号选择先写入配置；后端重启后由密钥/数据目录提取器确认所选账号，
得到 `bound_account` 和 `bound_pid`。UIA 驱动创建时带入这个 PID，主窗口、输入框和发送按钮都必须来自同一个 PID。
无法确认 PID 时返回 `ambiguous_process`；账号不一致时返回 `account_binding_mismatch`；找到 PID 但无法证明归属时返回
`account_binding_unverified`；窗口 PID 不一致时返回 `window_pid_mismatch`。

### 控件和发送动作

`foreground_uia` 会短暂激活已绑定窗口，但不移动鼠标、不使用坐标点击。发送链路依次检查主窗口、搜索框、聊天输入框，
通过 ValuePattern 写入并回读正文，再查找真正的发送按钮，优先调用 `InvokePattern`，其次调用
`LegacyIAccessible.DoDefaultAction`。只有显式配置 `send_key_fallback: enter` 或 `ctrl_enter` 才会使用按键兜底，默认关闭。

`background_uia` 不主动激活窗口，只接受已经 materialized 的 UIA 控件树；目标会话不在可见会话列表或控件树不可用时返回明确错误。
`auto` 模式可在尚未执行发送动作时切换到 `foreground_uia`，但不会回退到坐标点击、鼠标发送或键盘注入。

真实后台测试结果：

- `InvokePattern` 在当前微信版本上会触发窗口前置；发送器检测到前台句柄变化后返回 `background_input_state_changed`，不继续接受这次动作。
- `LegacyIAccessible.DoDefaultAction` 没有改变前台窗口、键盘焦点或鼠标坐标，但调用后输入框仍保留正文，微信没有产生可确认的发送记录。
- `PostMessage:WM_LBUTTON` 发送成功，输入框清空，微信数据库产生本人发送记录；前台窗口、焦点和鼠标坐标前后不变。

### 发送后确认和日志

UIA Pattern 调用成功不等于消息已经落盘。系统先记录 `invoke` 和 `ui_verify` 阶段，再使用严格的 `target_id` 查询目标会话的
消息表，只匹配本人发送、文本类型、时间窗口内且正文哈希一致的记录。查库未及时确认时返回 `pending_verify`；后续任务调用
`verify_pending_result()`，只读数据库，不会重新进入 UIA 发送路径。最终状态、错误阶段、错误码、目标 ID、内容哈希、尝试 ID
会写回同一条出站日志。监听器再次读到本人消息时，会按目标会话、正文哈希和 30 秒时间窗口认领出站尝试，并把真实
`Msg_*` 消息 ID写回同一行；找不到尝试时才创建 `database_observed` 出站兜底记录，不会创建 inbound 重复行。

## 风险与边界

- UIA 控件树可能因微信版本、窗口状态、语言或权限变化而改变，因此需要保留控件探测日志。
- 不应默认启用鼠标或坐标回退，否则无法证明后台 UIA 发送链路真实可用。
- 不应把收到消息日志中的群聊 ID 当作群成员 ID。
- 不应把数据库 `create_all()` 当作已有 SQLite 表的迁移方案。
- 真实联系人测试需要用户明确触发，开发阶段默认只做控件探测和文件传输助手测试。

## 本阶段验证

- `python -m compileall`：通过（UIA 发送器和 `SendResult`）。
- Python 3.12 依赖导入：通过，`pywin32`、`uiautomation`、`wechatauto` 来自 `D:\Wechat_bot\weix\venv`。
- 已安装 `pytest 9.1.1` 到当前 `venv`。
- 群聊解析专项测试：通过，`4 passed`。
- 消息日志迁移测试：通过，`1 passed`，重复执行迁移也通过。
- Windows 发送器与 UIA 单元测试：通过，最新专项 `27 passed`。
- 自动回复出站日志集成测试：通过，`8 passed`，验证 `generated -> sending -> sent`、`attempt_id` 和 `reply_to_msg_id`。
- 消息 API/手动发送日志测试：通过，`11 passed`。
- 前端 `npm run build`：通过；Vite 仅报告已有的大 chunk 警告。
- UIA 诊断、PID 解析和平台接口定向测试：通过，`6 passed`。
- UIA 检测界面前端构建：通过；Vite 仅报告已有的大 chunk 警告。
- Windows 数据目录、临时清理和截图测试已完成隔离修复，不再依赖宿主机真实微信目录或污染后续测试。
- 后端全量测试：`168 passed, 4 skipped`；4 个跳过项是默认关闭的真实微信集成测试，设置 `WEIX_RUN_LIVE_WECHAT_TESTS=1` 才会运行。
- Windows 真实机器只读验证：数据库诊断 `result: ok`（210 条消息、177 条文本消息）；UIA 绑定账号/PID/窗口 PID 一致；最大化后搜索框和会话列表可见；通过 UIA 打开“文件传输助手”成功；ValuePattern 草稿写入、回读、清空成功。
- Windows 真实发送隔离验证：前台 UIA 测试 `Weix UIA 焦点修复测试 2026-08-24 21:06:19` 返回 `send_not_accepted`；后台 `InvokePattern` 测试 `Weix 后台 UIA 静默发送测试 2026-08-24 21:19:56` 返回 `background_input_state_changed`；后台 Legacy 测试 `Weix Legacy 后台 UIA 测试 2026-08-24 21:26:38` 未抢前台但未发送。ValuePattern 对照实验写入成功但会前置窗口。
- UIA 真实后台发送和数据库回读闭环：已完成测试账号私聊验收；验证结果曾因数据库时间戳早于发送开始时间约 1 秒而误报，现已加入 3 秒容错。
- 出站消息日志合并专项测试：通过，验证真实 `Msg_*` ID 回写、旧 inbound 重复行清理和无尝试时的出站兜底。
- 消息日志和多账号状态改造后的全量回归：`168 passed, 4 skipped`；前端 `npm run build` 通过，Vite 仅报告已有的大 chunk 警告。

## 最近提交

- `0b5380a feat: add UIA diagnostics to chat config`
- `a1fa893 feat: add UIA diagnostics endpoint`
- `1db76cd feat: expose message delivery logs`
- `d26ff82 fix: settle pending deliveries without resending`
- `c9caba4 feat: expose delivery and UIA diagnostics in admin`
- `b05643f fix: recognize nested Windows 4.x message databases`
- `15c4580 fix: initialize UIA tree during diagnostics`
- `102c7a8 fix: restore foreground UIA navigation layout`
- `c4b5a5a fix: harden UIA navigation verification`
