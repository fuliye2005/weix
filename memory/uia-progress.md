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

UIA 的基础可用性已经确认：微信窗口的 UIA accessibility gate 可以被热激活，项目也已经存在发送按钮查找逻辑。当前发送流程已经接入 UIA 同步执行入口，会真正调用发送按钮的 Pattern，并返回分阶段结果；真实微信窗口和真实联系人仍未做最终验收。

目前尚未向真实联系人发送测试消息，不能把当前状态视为已经完成上线。

## 已完成

以下项目已经完成调查、代码确认或环境确认：

- [x] 确认项目当前使用 `wechatauto-replica 1.1.7`。
- [x] 确认项目当前使用 `uiautomation 2.0.29`。
- [x] 确认 UIA accessibility gate 可以热激活。
- [x] 确认当前配置为 `method: uia`。
- [x] 确认当前配置为 `background_mode: false`。
- [x] 确认当前配置为 `allow_mouse_fallback: false`。
- [x] 确认 `sender_windows_uia.py` 中已经存在 `_find_send_button()`。
- [x] 确认当前前台 UIA 路径不再默认使用 `SendKeys("{Enter}")`，按键仅作为显式配置的兜底。
- [x] 确认群聊数据库记录包含 `real_sender_id` 字段。
- [x] 确认当前群聊解析没有通过 `Name2Id.rowid` 映射真实发送者名称。
- [x] 确认群聊解析失败时会回退到群 ID，导致发送者名称显示成群聊名称。
- [x] 确认部分群消息正文仍包含 `wxid_xxx:\n` 形式的发送者前缀。
- [x] 确认当前 `messages` 表主要记录收到的消息，缺少完整的出站消息字段。
- [x] 确认已有 SQLite 数据库不能仅依赖 `create_all()` 自动增加新字段。
- [x] 确认 Python 3.12 虚拟环境位于 `D:\Wechat_bot\weix\venv`。
- [x] 确认 Python 3.13 环境调用 `_prepare_windows_imports()` 后可以找到 `win32ui`，问题重点在启动环境和导入路径。
- [x] 完成 UIA 结构化 `SendResult`，可以区分窗口、搜索、正文、调用和 UI 验证阶段。
- [x] UIA 发送优先查找真实“发送”按钮，并调用 `InvokePattern` / `LegacyIAccessible.DoDefaultAction`。
- [x] 修复 UIA 结构化发送结果调用了缺失同步入口的问题；现在 `foreground_uia`、`background_uia` 和 `auto` 都会进入统一的 UIA 执行器。
- [x] 增加输入框写入后的 ValuePattern 回读校验。
- [x] 增加 UIA 控件诊断方法，返回账号、PID、窗口、搜索框、输入框、发送按钮和 Pattern 信息。
- [x] 启动脚本改为固定使用 `venv\Scripts\python.exe`，并在启动前检查 UIA 依赖是否来自同一环境。
- [x] 从外部 Python 3.13 的 `_pth` 中移除 `venv-py313-stale` 路径。

## 尚未完成

以下项目仍未完成或尚未得到真实运行验证：

- [x] 让 UIA 发送流程实际调用发送按钮的 `InvokePattern`。
- [x] 为不支持 `InvokePattern` 的控件增加 `LegacyIAccessible.DoDefaultAction` 兼容路径。
- [x] 将 Enter/Ctrl+Enter 发送降级为显式配置项，而不是默认发送方式。
- [x] 增加发送前的窗口、会话、输入框和发送按钮校验。
- [x] 增加发送后的 UI 状态验证，确认输入框已清空或消息气泡已出现。
- [ ] 增加数据库验证，确认发送成功消息已经写入本地消息记录。
- [x] 增加结构化 `SendResult`，区分窗口、搜索、输入框、按钮调用、UI 验证和数据库验证阶段。
- [x] 修复群聊 `real_sender_id -> Name2Id.rowid -> user_name` 的发送者解析。
- [x] 统一群聊入站和出站正文清理，移除正文中的 `wxid_xxx:` 前缀。
- [x] 为 `messages` 表增加消息方向、发送状态、失败原因、发送时间和回复关联字段。
- [x] 编写数据库迁移脚本，兼容已经存在的 SQLite 数据库。
- [x] 在消息 API 中返回消息方向、发送状态、失败原因、错误阶段、尝试 ID 和发送者信息。
- [x] 在 `MessageLog.vue` 中增加发送/接收方向、状态、发送方式、回复来源和错误阶段展示。
- [x] 增加回复消息日志，确保规则/AI 生成的回复和实际发送结果分别可追踪。
- [ ] 增加多账号绑定、账号选择和账号在线状态的完整验证。
- [ ] 增加管理界面的 UIA 诊断入口和重启按钮。
- [x] 修改启动脚本，优先使用 `venv\Scripts\python.exe`。
- [x] 完成 Python 3.12 依赖导入验证，包括 `fastapi`、`win32ui`、`wechatauto` 和 `uiautomation`。
- [x] 增加 UIA 控件探测和发送流程单元测试。
- [ ] 在用户主动确认后，使用“文件传输助手”完成最小真实发送测试。
- [ ] 完成真实微信私聊和群聊发送验证。

## 技术实施顺序

1. 固定后端启动解释器和依赖环境。
2. 完成 UIA 控件探测与结构化发送结果。
3. 实现发送按钮 `InvokePattern` / `DoDefaultAction`。
4. 增加发送后的 UI 和数据库双重验证。
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
- Windows 发送器与 UIA 单元测试：通过，`16 passed`。
- 自动回复出站日志集成测试：通过，`8 passed`，验证 `generated -> sending -> sent`、`attempt_id` 和 `reply_to_msg_id`。
- 消息 API/手动发送日志测试：通过，`11 passed`。
- 前端 `npm run build`：通过；Vite 仅报告已有的大 chunk 警告。
- Windows 路径扫描全量测试仍有 2 项旧失败，原因是测试临时目录没有覆盖真实微信目录发现结果；与本次群聊解析改动无关。
- UIA 真实控件和数据库回读测试：尚未执行，仍不能据此宣称真实发送已完成。
