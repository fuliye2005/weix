# Weix Windows UIA 开发全过程

## 1. 文档信息

- 项目：`fuliye2005/weix`
- 工作目录：`D:\Wechat_bot\weix`
- 文档生成日期：2026-08-24
- 目标平台：Windows
- 目标客户端：Windows PC 微信，实机 UIA 验证以微信 4.1.12.26 界面为准
- 当前测试账号：`wxid_w6dljwmzzsl922_6b1b`
- 当前测试微信进程 PID：`24560`
- 当前测试目标：`芙莉叶`，`wxid_ybtkerfcizd422`
- Python 运行环境：项目内 `venv`，Python 3.12
- UIA 相关依赖：`uiautomation 2.0.29`、`wechatauto-replica 1.1.7`

本文记录 UIA 发送从需求分析、控件探测、账号绑定、前台失败、后台保护、最终发送成功，到发送验证和消息日志修复的完整过程。文档同时区分“代码已经完成”“测试账号已经验证”和“仍需要补充的真实验收”，避免把 UIA 函数调用成功误认为微信已经真正发送。

## 2. 最终结论

当前微信版本上，真正可用的主路径不是简单调用 `InvokePattern.Invoke()`，而是：

```
账号选择
  -> 数据库密钥与微信主进程绑定
  -> UIA 驱动按绑定 PID 获取微信窗口
  -> UIA 获取目标会话和聊天输入框
  -> UIA 写入正文并回读确认
  -> UIA 找到真实“发送”按钮
  -> 读取按钮 BoundingRectangle
  -> 将按钮中心点转换为主窗口客户区坐标
  -> 对微信主窗口投递 WM_LBUTTONDOWN / WM_LBUTTONUP
  -> 检查前台窗口、键盘焦点和鼠标坐标没有变化
  -> 检查输入框已经清空
  -> 检查消息列表出现本人发送正文
  -> 查询微信本地消息数据库确认本人消息落盘
```

当前推荐验收路径是“auto 优先后台，必要时前台 UIA”：

```yaml
windows_sender:
  method: uia
  send_mode: auto
  background_mode: false
  allow_foreground_activation: true
  background_post_message: true
  allow_mouse_fallback: false
  send_key_fallback: none
  require_ui_verify: true
```

这条路径具有以下特征：

- 不调用真实鼠标移动或物理点击。
- 不把微信窗口切到前台。
- 不抢当前用户正在使用的键盘焦点。
- 不使用 `SendKeys` 作为后台发送方式。
- 不依赖“函数没有抛异常”作为发送成功证据。
- 发送动作、UI 状态、消息数据库和消息日志分别有可诊断结果。
- 如果已经执行过发送动作，后续失败不会自动切换到另一条发送路径重发，避免重复消息。
- `auto` 即使探测到后台能力可用，也会保留前台 UIA 作为候选路径；只有后台尚未执行发送动作且没有触发输入状态保护时才允许切换。
- 只要后台动作改变了前台窗口、键盘焦点或光标状态，就立即熔断，不再为了“成功率”切换到前台重发。

测试账号上的后台 `PostMessage:WM_LBUTTON` 已成功发送文本；前台窗口句柄、键盘焦点和鼠标坐标在后台路径发送前后保持不变。`auto` 在后台能力不足或目标不可见时可以切换前台 UIA，但不回退鼠标或键盘。当前仍需要补充群聊对端可见性验收，以及微信升级后控件结构变化的回归。

## 3. 最初需求和约束

最初目标并不是单纯“让 Python 调一个发送函数”，而是把微信收发、AI 自动回复、管理界面和日志串成一个可以长期运行的系统。UIA 发送部分有几个硬约束：

1. 多个微信账号同时运行时，不能随机选择一个窗口。
2. 发送必须落到用户选择的账号和目标会话。
3. 尽量不前置微信窗口，不移动用户鼠标，不抢用户键盘。
4. 不能因为 UIA Pattern 返回 `True` 就直接写成“已发送”。
5. 发送失败时需要知道失败发生在窗口、搜索、正文、按钮调用、UI 验证还是数据库验证阶段。
6. 消息日志要区分收到和发出，并显示目标、发送方式、状态、尝试 ID 和真实微信消息 ID。
7. 监听器会从微信数据库读回当前账号自己发出的消息，不能把这条消息再次当作收到消息显示。
8. UIA 不可用时，不能偷偷降级到坐标点击或键盘注入，因为那会破坏“后台、不抢输入设备”的验收条件。

## 4. 原有系统与改造边界

项目原有的消息链路大致是：

```
微信数据库
  -> WindowsDBReader
  -> MessageMonitor
  -> AutoReplyPipeline
  -> 规则引擎 / AI Agent
  -> WindowsSender
  -> 微信窗口
```

本次 UIA 改造主要集中在以下层次：

| 层次 | 主要文件 | 责任 |
| --- | --- | --- |
| 平台发送门面 | `backend/app/core/sender_windows.py` | 兼容旧接口、选择 UIA 或鼠标模式、统一数据库验证 |
| UIA 发送器 | `backend/app/core/sender_windows_uia.py` | 账号绑定、控件查找、导航、写入正文、按钮发送、后台保护 |
| 账号和密钥绑定 | `backend/app/core/key_extractor_windows.py`、平台相关代码 | 识别微信进程、缓存密钥、绑定账号和 PID |
| 数据库读取 | `backend/app/core/db_reader_windows.py` | 读取消息、识别本人发送、解析群聊发送者 |
| 消息监听 | `backend/app/core/message_monitor.py` | 轮询、去重、过滤、把本人消息送入记忆通道 |
| 自动回复 | `backend/app/core/auto_reply_pipeline.py` | 生成回复、创建出站日志、发送、更新状态、合并本人回读消息 |
| 日志服务 | `backend/app/services/message_service.py` | 消息表写入、出站尝试生命周期、自发消息物化 |
| 管理接口 | `backend/app/api/platform_api.py` | UIA 诊断、账号状态、后端重启 |
| 管理界面 | `frontend/src/views/ChatConfig.vue`、`MessageLog.vue` | UIA 检测、账号切换、重启、消息日志展示 |

## 5. 账号选择和 PID 绑定

### 5.1 为什么不能只按窗口标题找微信

同时运行多个微信时，窗口标题可能相同，或者窗口层级、当前聊天和可见状态会变化。单纯调用“找微信窗口”可能把正文写入错误账号，甚至把消息发给错误账号。因此 UIA 驱动不能自行猜测窗口。

### 5.2 绑定流程

启动时先由 Windows 密钥提取器处理微信进程和本地数据库：

1. 枚举微信主进程。
2. 读取配置中选择的账号。
3. 从对应进程提取或加载数据库密钥。
4. 用密钥验证消息数据库。
5. 记录 `bound_account` 和 `bound_pid`。
6. UIA 驱动只接受这个 PID。

`_SelectedWeChatUIA` 对第三方驱动的 `_wechat_hwnds()` 做了约束，只保留 PID 与绑定 PID 一致的窗口。UIA 主窗口再次通过 `GetWindowThreadProcessId` 或控件的进程信息校验，确保窗口 PID 没有漂移。

### 5.3 绑定状态和错误码

系统不会在无法证明归属时继续发送，主要状态包括：

| 状态/错误码 | 含义 |
| --- | --- |
| `bound` | 所选账号、已绑定账号和 PID 一致 |
| `ambiguous_process` | 有多个微信进程，但没有确认选择哪个账号 |
| `account_binding_mismatch` | 所选账号与已绑定账号不一致 |
| `account_binding_unverified` | 找到了 PID，但无法证明属于所选账号 |
| `window_pid_mismatch` | UIA 找到的窗口不属于绑定 PID |
| `binding_unavailable` | 无法读取绑定状态 |
| `uia_window_unavailable` | 绑定状态正常，但 UIA 主窗口不可访问 |

账号或 PID 发生变化时，UIA 驱动缓存会重新建立。管理界面保存新账号后必须重启后端，使数据库读取器、消息监听器和发送器全部切换到同一账号。

## 6. UIA 控件探测过程

### 6.1 探测顺序

UIA 不依赖坐标寻找发送控件，而是从微信控件树逐层确认：

1. `mmui::MainWindow` 主窗口。
2. 会话列表 `AutomationId=session_list`。
3. 搜索框。
4. 当前会话标题。
5. 聊天输入框。
6. 输入框父级容器中的真实发送按钮。
7. 消息列表，用于发送后 UI 验证。

后台模式不调用会主动激活窗口的 `ensure_window()`，而是只接受已经 materialized 的 UIA 控件树。找不到已经存在的窗口或控件时，后台模式直接失败。

### 6.2 真实发送按钮的识别

`_find_send_button()` 首先从聊天输入框向上遍历父控件，在当前输入区域查找名称为以下之一的按钮：

- `发送`
- `发送(S)`
- `Send`

如果父级容器找不到，再在主窗口范围内查找。这样可以减少误把其他工具按钮当成发送按钮的风险。

### 6.3 实机探测到的按钮信息

测试账号上读取到的发送按钮具有以下特征：

- UIA 类型：`ButtonControl`
- 类名：`mmui::XOutlineButton`
- 框架：`Qt`
- 原生 HWND：`0`
- 可用 Pattern：`ValuePattern`、`InvokePattern`、`LegacyIAccessible`
- Legacy 默认动作：`按`
- 具有可读的 `BoundingRectangle`

这里有一个关键结论：按钮没有独立的原生 HWND，但它有 UIA 控件边界。因此不能把按钮当成普通 Win32 子窗口直接 `SendMessage`，最终方案是用 UIA 找到按钮的屏幕矩形，再将矩形中心转换为微信主窗口客户区坐标，向主窗口投递鼠标消息。

### 6.4 管理界面诊断

后端提供：

```
GET /api/platform/uia/diagnose
```

管理界面的“聊天配置”页提供“UIA 检测”按钮，显示：

- 选中账号
- 已绑定账号
- 绑定 PID
- 驱动 PID
- UIA 主窗口 HWND、PID、类名和标题
- 当前会话
- 会话列表
- 搜索框 Pattern
- 聊天输入框 Pattern
- 发送按钮 Pattern
- Legacy 元数据、BoundingRectangle 和错误码

诊断接口只读控件树，不发送消息，不主动移动鼠标，也不应该因为诊断而改变用户前台窗口。

## 7. 前台 UIA 路径

### 7.1 前台路径的设计

前台 `foreground_uia` 允许短暂激活绑定的微信窗口，用于恢复控件树和导航布局，但仍然不使用物理鼠标坐标点击。必要时通过 Win32 `ShowWindow(SW_MAXIMIZE)` 恢复左侧搜索框、会话列表和右侧聊天区，避免窄窗口导致控件不可见。

前台路径的正文写入优先使用 `ValuePattern`。如果 ValuePattern 不可用或失败，可以在显式允许的前台模式中使用焦点、剪贴板和 `SendKeys` 作为写入回退。发送键盘兜底只有在配置明确设置 `send_key_fallback: enter` 或 `ctrl_enter` 时才允许。

### 7.2 前台导航校验

搜索结果不直接盲点。流程会：

1. 写入搜索关键词。
2. 收集搜索结果。
3. 群聊优先限定“群聊”分区。
4. 同名结果超过一个时返回 `ambiguous_search_result`。
5. 调用结果控件的 UIA action。
6. 读取当前聊天标题。
7. 确认聊天输入框出现。

只有标题与期望目标一致、输入框可用时，才认为导航成功。

### 7.3 前台真实失败

实机发现当前微信自绘 Qt 控件的 UIA Pattern 存在“调用成功但业务没有执行”的情况：

- `InvokePattern.Invoke()` 返回成功，但输入框正文没有清空。
- `LegacyIAccessible.DoDefaultAction()` 可以返回调用结果，但微信没有真正接受发送。
- 因此“Pattern 调用返回 True”不能作为发送成功条件。

系统后来增加了发送后的草稿清空检查。如果输入框没有清空，返回：

```
stage=ui_verify
error_code=send_not_accepted
```

同时，已执行过按钮动作后不允许自动切换到鼠标路径或重新完整发送，防止一次失败验证导致两条消息。

## 8. 后台 UIA 路径

### 8.1 后台模式的硬保护

后台模式的目标是“微信可以在后台运行，但发送不打扰用户当前操作”。因此所有关键阶段都会记录前台输入状态：

```
foreground_hwnd
focus_hwnd
cursor_x
cursor_y
```

在以下阶段之后检查状态是否变化：

- 找到窗口后
- 打开目标会话后
- 写入正文后
- 投递发送动作后

任一阶段发生变化，直接返回：

```
error_code=background_input_state_changed
```

这是一种 fail-closed 保护：宁可这次发送失败，也不接受已经前置窗口、改变焦点或移动鼠标的动作。

### 8.2 后台导航

后台模式不能依赖会激活窗口的搜索框操作，因此优先从已经存在的 `session_list` 中查找可见会话：

1. 读取可见会话项。
2. 按目标显示名或 `AutomationId` 匹配。
3. 必须恰好匹配一项。
4. 通过 UIA Pattern 调用会话项。
5. 检查当前聊天标题和聊天输入框。

如果目标会话不在当前可见会话列表中，后台模式会返回 `search_result_not_found` 或 `ambiguous_search_result`，不会偷偷打开搜索框、前置窗口或退回鼠标操作。

### 8.3 后台正文写入

后台模式只允许通过 UIA Legacy Value 接口写入正文：

```python
legacy_pattern.SetValue(text)
```

后台模式不允许：

- `SetFocus()`
- `SendKeys`
- 物理剪贴板粘贴
- Ctrl+V
- pyautogui

写入后立即读取 ValuePattern 或 Legacy Value 回读，并与规范化后的原文比较。回读不一致时返回 `draft_readback_mismatch`。

### 8.4 发送按钮动作的演进

后台发送经历了三种方案：

#### 方案 A：`InvokePattern`

优点是 API 语义最直接；问题是实机上会把微信窗口切到前台，触发输入状态守卫，返回 `background_input_state_changed`。因此它不能作为当前后台主路径。

#### 方案 B：`LegacyIAccessible.DoDefaultAction`

它不一定前置窗口，但在当前微信版本上调用后输入框仍保留正文，微信没有产生可确认的发送记录。它可以用于诊断或备用尝试，但不能单独判定发送成功。

#### 方案 C：向 UIA 发现的按钮投递 `WM_LBUTTONDOWN/WM_LBUTTONUP`

这是最终验证成功的方案：

1. UIA 发现真实发送按钮。
2. 读取按钮 `BoundingRectangle`。
3. 计算矩形中心点。
4. 调用 `ScreenToClient(main_hwnd, point)` 将屏幕坐标转换为微信主窗口客户区坐标。
5. 构造 `lParam=(y << 16) | x`。
6. 调用：

```
PostMessageW(main_hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lParam)
PostMessageW(main_hwnd, WM_LBUTTONUP, 0, lParam)
```

7. 发送前后检查前台窗口、焦点和鼠标位置。
8. 等待输入框清空。
9. 检查 UI 消息列表和本地数据库。

这不是把物理鼠标移动到按钮再点击。鼠标位置只用于测试保护，不会被修改；按钮矩形只是 UIA 提供的逻辑命中区域，消息直接投递给微信主窗口。

## 9. 发送结果状态机

所有新发送路径都返回 `SendResult`，而不是只有一个布尔值。

### 9.1 主要状态

| 状态 | 含义 |
| --- | --- |
| `generated` | 已创建出站尝试，但尚未触碰微信 UI |
| `sending` | 正在执行发送动作 |
| `sent` | UI 和数据库验证完成 |
| `pending_verify` | UI 动作已完成，但数据库暂时没有确认 |
| `failed` | 某一阶段明确失败 |
| `skipped` | 由于目标不可搜索、权限或安全规则主动跳过 |

### 9.2 主要阶段

| 阶段 | 典型错误 |
| --- | --- |
| `window` | `ambiguous_process`、`window_not_found`、`window_pid_mismatch` |
| `search` | `search_result_not_found`、`ambiguous_search_result`、`chat_open_verification_failed` |
| `draft` | `input_not_found`、`draft_write_failed`、`draft_readback_mismatch`、`input_focus_failed` |
| `invoke` | `send_button_not_found`、`background_button_message_failed`、`background_input_state_changed` |
| `ui_verify` | `send_not_accepted`、`ui_message_not_found` |
| `db_verify` | `db_not_confirmed`、`target_id_required` |

### 9.3 不重复发送原则

`auto` 模式只有在前一条路径还没有执行发送动作、没有清空草稿时，才可以尝试下一候选路径。一旦 `action_performed=True` 或 `draft_cleared=True`，后续失败只记录失败，不重新发送。

这个规则解决了一个很危险的问题：第一次 UIA 调用其实已经把消息发出，但验证阶段误报失败；如果系统马上换另一条路径重发，用户会收到两条相同消息。

## 10. 发送后的三层验证

### 10.1 调用层验证

记录按钮调用是否返回成功，以及具体调用方法：

- `LegacyIAccessible.DoDefaultAction`
- `InvokePattern`
- `SelectionItemPattern`
- `PostMessage:WM_LBUTTON`
- 显式启用时的 `key:enter` 或 `key:ctrl_enter`

### 10.2 UI 层验证

调用完成后等待：

1. 输入框正文被微信消费，Value 变为空。
2. 消息列表出现规范化后的本人发送正文。

Pattern 返回成功但输入框不为空时，结果是 `send_not_accepted`，不是 `sent`。

### 10.3 数据库层验证

`WindowsSender._reader_has_recent_self_text()` 使用严格条件查询微信本地消息库：

- 必须有 `target_id`，禁止跨会话匹配。
- 只查目标会话对应的消息分表。
- 只查文本消息。
- 只接受本人发送行。
- 正文规范化后必须一致。
- 旧版表结构会使用 `is_sender=1` 和 `msg_talker` 过滤。
- Windows 4.x 分表会检查 `real_sender_id`、`status`、`origin_source`、`server_seq`。

实机记录中的本人发送行曾表现为：

```
real_sender_id=2
status=2
origin_source=1
server_seq=0
```

微信有时会先写消息库，再返回 UIA 调用结果，因此数据库 `create_time` 可能比发送开始时间早约 1 秒。当前查询起点向前容错 3 秒，但仍保留目标会话、本人发送和正文哈希约束，避免扩大成跨会话误判。

### 10.4 Pending 验证

如果 UI 已显示发送动作和草稿清空，但数据库暂时没有记录，返回 `pending_verify`。后台任务随后只执行数据库查询：

```
pending_verify
  -> verify_pending_result()
  -> 只读数据库
  -> sent 或继续 pending_verify
```

pending 任务绝不重新调用 UIA 发送路径。

## 11. 为什么消息日志会出现两行

### 11.1 旧逻辑的重复来源

一次发送原本会先创建：

```
outbound:<attempt_id>
```

之后 `MessageMonitor` 从微信数据库读到当前账号自己的 `Msg_*` 记录。监听器正确识别了 `is_self=True`，但旧版 `_persist_message()` 仍然无条件调用普通 `save_message()`，所以又创建：

```
Msg_<table>:<local_id>  direction=inbound
```

结果就是管理界面显示一行“发出”和一行“收到”。这不是微信实际发送了两遍，而是同一条消息被日志层写了两次。

### 11.2 当前修复

新增 `MessageService.materialize_self_message()`，本人消息走专用逻辑：

1. 计算正文哈希。
2. 根据私聊目标 `sender` 或群聊目标 `room_id` 确认会话。
3. 在前后 30 秒内查找相同目标、相同正文哈希的 outbound 尝试。
4. 找到时把临时 `outbound:<attempt_id>` 改成真实 `Msg_*` ID。
5. 把状态收敛为 `sent`，清除 `db_not_confirmed` 等暂态错误。
6. 使用微信数据库的实际时间更新日志时间。
7. 如果旧版本已经存在同一 `Msg_*` inbound 行，删除重复 inbound 行后再把真实 ID写回 outbound 行。
8. 如果没有对应的 outbound 尝试，创建一条 `direction=outbound`、`send_method=database_observed` 的兜底记录。

因此新日志只保留一行：

```
Msg_<table>:<local_id>  direction=outbound  status=sent
```

当前数据库检查到的历史数据中，有 7 组符合“同目标、同正文、相差约 1 秒”的旧重复配对。代码已经具备修复能力；一次性清理历史数据时必须使用同样的严格匹配条件，不能按姓名或模糊正文批量删除。

## 12. 群聊身份修复

群聊中 `room_id` 是群会话 ID，不是消息发送者。旧数据或旧版微信可能出现：

```
sender_wxid = room@chatroom
content = wxid_member:\n你好
```

这会导致管理界面把群名称显示成发送者，并把发送者 ID 留在内容中。

当前处理包括：

- 优先使用 Windows 4.x 的 `real_sender_id`。
- 通过 `Name2Id.rowid -> user_name` 映射真实成员。
- 从旧正文中解析 `wxid_xxx:\n` 前缀。
- `normalize_group_message()` 清理前缀。
- 当无法确认成员时返回空发送者，而不是把 `room_id` 冒充成员。
- API 序列化时兼容性修复历史群聊记录。
- 前端分别显示群名、发送者名称和发送者 ID。

这部分和 UIA 发送的关系是：发送时用群名或群 ID打开目标会话，日志入站侧必须单独解析真实发言人，不能把发送目标和发送者混成同一个字段。

## 13. 管理界面和重启能力

### 13.1 UIA 诊断

`ChatConfig.vue` 中提供 UIA 检测按钮，调用后端诊断接口，显示账号、PID、窗口、当前会话和控件 Pattern。诊断是只读的，不执行发送。

### 13.2 后端重启

账号切换后，单纯修改配置不足以切换已打开的数据库和 UIA 驱动，因为流水线、监听器和驱动对象都可能持有旧账号状态。管理界面提供：

```
POST /api/platform/restart
```

重启会重新：

- 读取配置。
- 初始化数据库。
- 绑定所选微信账号和 PID。
- 打开消息数据库。
- 建立名称映射。
- 创建消息监听器。
- 创建 UIA 发送器。
- 启动自动回复流水线。

启动脚本固定使用：

```
venv\Scripts\python.exe
```

避免外部 Python、嵌入式 Python 和项目虚拟环境混用，导致 `pywin32`、`uiautomation` 或 UIA 依赖加载到错误版本。

## 14. 关键提交时间线

下面按功能演进记录主要提交。完整历史仍以 Git 为准。

| 提交 | 主要内容 |
| --- | --- |
| `131eee5` | 增加 Windows 多账号微信支持，建立账号选择基础 |
| `8f89e71` | 修复打包 Windows 运行时的 UIA 导入问题 |
| `6784277` | 强化 UIA 发送器并固定 Windows 运行时 |
| `787b1c2` | 固定并校验 Windows UIA 运行时依赖 |
| `4ea2446` | 增加消息投递日志表结构和迁移基础 |
| `3938ccb` | 增加出站消息日志生命周期 |
| `2d1aeba` | 把 UIA 发送结果接入实际执行路径 |
| `1db76cd` | 暴露消息投递日志 API 和前端展示 |
| `a1fa893` | 增加 UIA 诊断接口 |
| `0b5380a` | 增加管理界面的 UIA 检测按钮和结果弹窗 |
| `c4b5a5a` | 强化 UIA 导航目标校验，防止同名误命中 |
| `102c7a8` | 修复前台 UIA 窄窗口布局和导航控件可见性 |
| `1b6706a` | 记录真实机器只读 UIA 验证结果 |
| `97bcc43` | 修复前台发送前输入框焦点问题 |
| `81f1be3` | 将后台 UIA 设为默认方向 |
| `ab96628` | 增加后台 UIA 前台输入状态保护 |
| `b26b599` | 后台 UIA 优先 Legacy action |
| `32d9639` | 记录 UIA 真实发送测试证据 |
| `18ba659` | 增加无输入设备的后台按钮投递方案 |
| `48d4bac` | pending 验证只查库，不重复发送 |
| `a97fb0c` | 发送按钮动作增加真实后置验证 |
| `7672085` | 暴露发送按钮的 UIA 结构化诊断信息 |
| `6a85874` | 容忍微信消息数据库时间戳顺序偏差 |
| `cf09305` | 把本人回读消息合并到 outbound，修复日志双行问题 |

## 15. 实机测试证据

### 15.1 只读 UIA

已验证：

- UIA accessibility gate 可以热激活。
- 所选账号、绑定账号、绑定 PID 和窗口 PID 一致。
- UIA 可以找到微信主窗口。
- 窄窗口恢复后搜索框和会话列表可见。
- 可以通过 UIA 打开“文件传输助手”等目标会话。
- 输入框 ValuePattern/Legacy Value 可以写入并回读正文。
- 输入框可以清空。

### 15.2 失败路径对照

| 测试 | 结果 |
| --- | --- |
| 前台 `InvokePattern` | 调用返回，但正文没有被微信消费，`send_not_accepted` |
| 后台 `InvokePattern` | 会改变前台输入状态，`background_input_state_changed` |
| 后台 `LegacyIAccessible.DoDefaultAction` | 不抢前台，但微信没有实际发送 |
| 后台 `PostMessage:WM_LBUTTON` | 成功发送并通过 UI/数据库验证 |

### 15.3 后台成功验收

测试消息：

```
Weix 后台 PostMessage 验收测试 2026-08-24 23:04:29
```

验收结果：

```
action_performed=true
draft_cleared=true
ui_verified=true
```

数据库中出现了本人发送行，实测：

```
real_sender_id=2
status=2
origin_source=1
server_seq=0
```

发送前后：

- 前台窗口 HWND 不变。
- 键盘焦点 HWND 不变。
- 鼠标坐标不变。
- 微信数据库产生对应文本消息。

### 15.4 自动化测试

当前全量后端回归：

```
168 passed, 4 skipped
```

4 个跳过项是默认关闭的真实微信集成测试。专项结果包括：

- Windows 发送校验测试：19 passed。
- 消息服务、自动回复、消息 API 和迁移专项：18 passed。
- 出站日志合并测试覆盖真实 `Msg_*` ID回写。
- 旧 inbound 重复行清理测试通过。
- 无 outbound 尝试时的出站兜底测试通过。

本轮新增的自动化覆盖：

- `auto` 在后台能力可用时仍保留前台 UIA 候选，后台能力不足时只在明确允许时进入前台 UIA。
- 后台 UIA 改变全局输入状态后不会继续尝试前台路径，避免同一条消息被二次发送。
- 前台 Pattern 假成功、输入框未清空时，会尝试 UIA 发现的发送按钮对应的 `PostMessage:WM_LBUTTON`，而不是物理鼠标点击。
- 消息列表已经出现正文但草稿仍未清空时，会返回 `send_state_ambiguous` 并停止重试，防止重复消息。
- 启动运行时拒绝 32 位 Python，并在日志中记录 Python 位数，避免 UIA/pywin32 二进制 ABI 不匹配。

本轮实际执行命令：

```powershell
venv\Scripts\python.exe -m pytest -q
```

结果为 `168 passed, 4 skipped`。跳过项仍然是默认关闭的真实微信集成测试，不能把自动化测试通过等同于所有微信版本和所有聊天类型都已实机验收。

## 16. 当前配置说明

版本库示例配置使用自动 UIA 路径：

```yaml
windows_sender:
  method: uia
  send_mode: auto
  background_mode: false
  allow_foreground_activation: true
  ensure_full_layout: true
  allow_mouse_fallback: false
  send_key_fallback: none
  background_post_message: true
  require_ui_verify: true
  input_verify_timeout: 3.0
  ui_verify_timeout: 4.0
  pending_verify_retries: 2
```

字段含义：

| 配置项 | 含义 |
| --- | --- |
| `method` | 发送门面选择 UIA |
| `send_mode` | `background_uia`、`foreground_uia` 或 `auto` |
| `background_mode` | 兼容旧配置的后台开关 |
| `allow_foreground_activation` | 是否允许 `auto` 在后台能力不足时使用前台路径 |
| `ensure_full_layout` | 前台导航时是否恢复微信完整布局 |
| `allow_mouse_fallback` | UIA失败时是否允许鼠标回退，当前应为 `false` |
| `send_key_fallback` | 前台显式键盘兜底，后台应为 `none` |
| `background_post_message` | 后台使用按钮 WM_LBUTTON 消息投递 |
| `require_ui_verify` | 是否要求消息列表出现本人正文 |
| `pending_verify_retries` | 数据库延迟时只读查询的重试次数 |

本地 `config/config.yaml` 通常被 Git 忽略。示例配置的修改不会自动覆盖本地配置；切换账号或发送模式后，需要在管理界面重启后端。

## 17. 故障排查顺序

遇到“输入框有内容但没发出”时，按下面顺序判断：

1. 打开管理界面的 UIA 检测，确认 `binding_status=bound`。
2. 确认 `bound_pid`、`driver_pid`、窗口 PID 一致。
3. 确认当前会话标题和目标名称一致。
4. 确认聊天输入框存在并且 Legacy Value 可写。
5. 确认发送按钮名称、类名和 Pattern 没有变化。
6. 确认后台状态守卫没有报 `background_input_state_changed`。
7. 看 `action_performed` 和 `invoke_method`，确认是否真的投递了 `PostMessage:WM_LBUTTON`。
8. 看 `draft_cleared`，如果为 `false`，说明微信没有消费正文。
9. 看 `ui_verified`，如果为 `false`，说明 UI 列表没有出现本人消息。
10. 看 `db_verified`，如果为 `false`，先判断是否处于数据库延迟或目标 ID 错误。
11. 检查消息日志是否只有一条 outbound；若出现 inbound 同内容，确认后端是否已经加载包含 `materialize_self_message()` 的版本。

常见错误与动作：

| 错误 | 首要检查 |
| --- | --- |
| `ambiguous_process` | 选择账号并重启后端 |
| `account_binding_mismatch` | 当前配置账号和密钥绑定账号不一致 |
| `window_pid_mismatch` | 微信重启或多开后重新绑定 |
| `navigation_controls_missing` | 微信窗口布局、权限或版本变化 |
| `search_result_not_found` | 后台目标不在可见会话列表，切换到允许前台导航的模式进行诊断 |
| `ambiguous_search_result` | 同名联系人/群聊，需要使用更稳定的显示名或 ID 映射 |
| `draft_readback_mismatch` | UIA Value 写入失败或控件结构变化 |
| `send_not_accepted` | Pattern 调用无效，确认后台是否使用 PostMessage |
| `background_input_state_changed` | 某个动作前置窗口、改变焦点或移动光标，后台模式拒绝继续 |
| `db_not_confirmed` | 检查目标 ID、数据库时间戳和消息分表 |
| `target_id_required` | 禁止无目标 ID 的宽范围发送验证 |

## 18. 仍未完成的事项

以下事项没有在本文中提前标记为完成：

- 完成群聊真实对端可见性的后台发送验收。
- 覆盖微信升级、窗口重启、会话切换和 UIA 控件名称变化。
- 将当前数据库中已经存在的历史重复配对做一次严格、可回滚的清理。
- 完善后台模式下目标不在可见会话列表时的无前台导航方案。
- 在不同微信权限级别、桌面锁屏和管理员权限组合下做回归。
- 对 `PostMessage` 在不同 DPI 缩放和多显示器坐标下做更广泛验证。

## 19. 本轮实现补强

本轮在已有 UIA 闭环之上继续处理了几个容易造成误判或重复发送的边界：

### 19.1 `auto` 不再在后台成功探测后放弃前台候选

早期 `auto` 的候选列表在后台能力探测成功时只有：

```text
background_uia
```

这会导致后台控件树在发送阶段临时不可用时直接失败，即使配置允许前台 UIA，也不会有第二条 UIA 路径。现在的候选选择是：

```text
background_uia -> foreground_uia
```

但这不是无条件重试。后台路径必须在以下条件全部满足时才允许切换：

1. 尚未执行按钮动作。
2. 输入框尚未被清空。
3. 没有发现 UI 消息已经出现正文。
4. 没有触发 `background_input_state_changed`。

一旦后台调用已经可能改变了微信状态，系统宁可返回失败并保留诊断证据，也不把同一正文交给第二条路径再次发送。

### 19.2 前台 UIA 也优先使用无输入设备的按钮投递

前台 UIA 允许短暂激活窗口，所以它可以用于恢复导航布局；但发送动作仍不默认依赖物理坐标点击。当前实现的顺序是：

1. 尝试 UIA 暴露的 Pattern。
2. 等待草稿清空。
3. 如果 Pattern 返回成功但草稿没有清空，检查消息列表是否已经出现正文。
4. 如果没有进入“消息已出现但状态不明确”的危险状态，再使用 UIA 找到的按钮矩形投递 `WM_LBUTTONDOWN/WM_LBUTTONUP`。
5. 再次验证草稿清空和消息列表。

这样保留了前台 UIA 的导航能力，同时避免把“Pattern 返回成功”误当成业务成功，也避免直接调用真实鼠标。

### 19.3 后台输入状态变化时立即熔断

后台保护以前已经能发现前台窗口、焦点和鼠标坐标变化；本轮进一步规定：

```text
background_input_state_changed -> stop all remaining candidates
```

原因是状态变化说明某个动作已经突破了后台约束。此时切换到前台 UIA 可能会把一次“已经部分执行”的消息再次发送，风险高于一次失败。因此 `auto` 不再继续尝试。

### 19.4 识别“消息已出现但草稿未清空”的不确定状态

如果消息列表已经出现待发送正文，但输入框仍保留原文，系统无法安全判断第一次按钮动作到底是成功、延迟还是 UI 状态不同步。实现将其标记为：

```text
stage=ui_verify
error_code=send_state_ambiguous
```

并停止后续动作。这条规则优先保护消息不重复，而不是盲目追求单次请求返回成功。

### 19.5 启动时固定 64 位 Python

UIA 依赖 `pywin32`、`uiautomation` 和第三方微信驱动，其中部分组件包含与 Python ABI、进程位数相关的二进制模块。仅检查 Python 版本号不够，32 位 Python 也可能显示为 3.12，但无法安全加载当前 x64 依赖。

现在启动检查同时验证：

- Python 主版本和次版本必须为 3.12。
- Python 指针宽度必须为 64 位。
- `pywin32`、`uiautomation`、`wechatauto-replica` 版本必须匹配。
- 关键模块必须来自当前项目虚拟环境。
- `.pyd` ABI 必须与 `cp312` 匹配。

不满足条件时后端在启动阶段明确失败，并记录解释器路径、位数、依赖版本和模块来源，避免运行到 UIA 发送阶段才出现难以理解的控件错误。

## 20. 从“能调用”到“能证明发送”的判断标准

整个开发过程最终形成了四个层次的判断：

| 层次 | 能证明什么 | 不能单独证明什么 |
| --- | --- | --- |
| 控件探测 | 找到了正确账号窗口、输入框和发送按钮 | 消息已经发送 |
| Pattern/窗口消息调用 | 发送动作被提交给微信 UI | 微信已经消费正文、对方已经看到 |
| UI 验证 | 草稿被消费、消息列表出现本人正文 | 数据库已经落盘、日志已正确合并 |
| 数据库和日志验证 | 目标会话中出现本人消息，日志可追溯且不重复 | 对方设备一定已经联网并展示 |

因此项目把 `sent` 定义为经过 UI 和数据库验证的状态，而不是 Python 调用没有抛异常的状态。`pending_verify` 表示动作和 UI 证据已经存在，但消息数据库还没有及时确认；它只允许后台查库收敛，不允许重新触发发送。

## 21. 当前交付状态

截至 2026-08-24，本地代码和文档状态如下：

### 已完成并有测试或实机证据

- 多账号选择、账号/PID 绑定和窗口 PID 校验。
- UIA 控件诊断和管理界面入口。
- 前台 UIA 导航、输入框写入和正文回读。
- 后台 UIA 的输入设备保护。
- 后台 `PostMessage:WM_LBUTTON` 私聊发送闭环。
- UI、数据库、pending 三层发送验证。
- 出站日志生命周期和本人消息回读合并。
- 群聊日志中的发送者身份与正文前缀修复。
- 管理界面后端重启能力。
- 64 位 Python 和 UIA 运行时一致性检查。
- 全量自动化回归：`168 passed, 4 skipped`。

### 仍需要实机完成

- 群聊中由其他成员设备确认消息可见的完整发送验收。
- 连续多条私聊和群聊压力验收，确认没有重复发送、串账号或串会话。
- 微信重启、窗口最小化、会话切换、多 DPI、多显示器和不同权限组合下的回归。
- 历史数据库中 7 组旧重复日志的备份、严格匹配清理和清理后复核。
- 微信升级后 UIA 控件树、按钮名称和 `PostMessage` 命中行为的回归。

这些事项不影响当前测试账号上已经完成的私聊后台 UIA 闭环，但影响把它作为所有微信版本和所有群聊场景的通用生产方案。

## 22. 相关代码入口

| 文件 | 入口 |
| --- | --- |
| `backend/app/core/sender_windows_uia.py` | `WindowsUIASender.send_text_result()`、`_send_text_once()`、`_post_button_message_without_mouse()` |
| `backend/app/core/sender_windows.py` | `WindowsSender.send_text_result()`、`verify_pending_result()`、`_reader_has_recent_self_text()` |
| `backend/app/core/auto_reply_pipeline.py` | `_create_outbound_reply_log()`、`_update_outbound_reply_log()`、`_persist_message()` |
| `backend/app/services/message_service.py` | `create_outbound_attempt()`、`update_outbound_attempt()`、`materialize_self_message()` |
| `backend/app/core/message_monitor.py` | `_should_process()`、`_is_recent_sent_message()` |
| `backend/app/core/db_reader_windows.py` | `_query_v4_messages_since()`、`_is_self_sent_v4_row()`、`_resolve_v4_group_sender()` |
| `backend/app/api/platform_api.py` | `/platform/uia/diagnose`、`/platform/restart` |
| `frontend/src/views/ChatConfig.vue` | UIA 检测、账号切换和后端重启 |
| `frontend/src/views/MessageLog.vue` | 出站/入站日志、状态和诊断详情 |
| `config/config.example.yaml` | Windows UIA 示例配置 |

## 23. 结语

这次 UIA 开发的核心不是找到一个能返回 `True` 的调用，而是建立一条可以证明“发给了正确账号、正确会话、没有打扰用户、微信确实消费了正文、消息确实落库、日志没有重复”的完整链路。

最终有效的技术路线可以概括为：

```
严格账号绑定
  + 只读 UIA 控件探测
  + Legacy Value 写入
  + UIA 发现按钮
  + PostMessage 投递按钮消息
  + 前台输入状态守卫
  + 草稿清空验证
  + UI 消息列表验证
  + 数据库本人消息验证
  + 出站日志物化和去重
```

其中任何一环不成立，发送结果都不能直接标记为成功。
