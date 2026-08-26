# 更新日志

## 2026-08-26

### Embedding 与联网搜索配置

- AI 配置页支持选择本地 Embedding 或 DashScope、SiliconFlow、OpenAI 云端 Embedding。
- 云端 Embedding 使用独立的供应商、模型、Base URL 和 API Key，不会误用其他聊天服务的密钥。
- 按供应商和模型隔离 ChromaDB 向量库，避免不同维度的向量混用。
- 云端 Embedding 模式跳过本地模型下载；旧配置仍兼容本地 Embedding。
- 启用按需联网搜索，用于明确搜索请求、新游戏、新词、缩写和需要确认时效性的内容；普通聊天不会默认搜索。
- 补充 `ddgs` 依赖，并纳入 Windows PyInstaller 桌面包，确保发布版也能使用联网搜索。
- 验证：云端 Embedding 配置读取、搜索工具实际调用和桌面包资源均已检查通过。

### Windows 桌面发布包

- 重新构建 `dist\\Weix\\Weix.exe`，包含最新前端、云端 Embedding 配置界面和联网搜索依赖。
- 桌面版仍从自身可写配置目录读取配置；本地 `config.yaml`、`.env`、数据库、密钥和聊天记录不纳入 Git 提交。

### 已知限制

- DashScope Embedding 仍需要用户在管理界面或环境变量中填写有效的 `DASHSCOPE_API_KEY`。
- 联网搜索依赖外部搜索服务和本机网络；搜索失败时机器人应明确说明无法确认，不应编造结果。
- 当前发送链路已有 UIA 输入校验、发送按钮调用和数据库确认，但重复发送保护、发送失败重试记录及发送前后截图仍在规划中。

## 2026-08-22

### 新增历史聊天模仿模式

- 本人 Skill 新增 `persona`、`replay`、`hybrid` 三种可选模仿方式。
- 外部聊天 JSON 继续使用 `senderUsername` 识别人物，保留来源文件、原始顺序、会话和群聊/私聊场景元数据。
- 新增 `backend/app/ai/persona_replay.py`，使用本地中文字符 n-gram、词项重合和场景权重建立“上下文 → 目标人物回复”索引。
- `replay` 模式将索引保存到本地 `data/persona_replay.json`，不初始化 LLM；没有可靠匹配时不回复。
- `hybrid` 模式支持历史原话直接复用、few-shot 表达参考和 Persona 回退。
- 增加重复回复冷却、短无意义回复过滤、当前消息相同文本过滤和跨文件/跨会话隔离。
- Persona 管理界面增加模仿方式、历史匹配阈值、上下文条数、参考样本数和重复冷却配置。
- 清除 Persona 时同时清理历史复用索引；现有旧版 Persona 缓存默认按 `persona` 模式兼容读取。
- 导入时继承顶层会话 ID 和群聊标记，并在 Persona 元数据中保留目标人物稳定 ID；运行时读取缓存不初始化 LLM，确保 `replay` 无 API Key 也能工作。
- `replay` 管理页面的读取、编辑和清理接口也改为只读加载缓存；同时过滤撤回提示及常见系统/媒体记录。
- 清除 Persona 时同步失效内存中的 replay 引擎；删除临时导入文件时明确提示已生成的历史索引是否保留。
- 验证：Persona/replay 相关后端专项测试 30 项通过，前端构建、Python 编译和差异检查通过；真实两组 JSON 建立 7,392 组历史样本并成功命中。
- 未修改微信数据库发送逻辑，未启用鼠标发送，也未进行真实联系人发送测试。

### 修复 Windows UIA 群聊发送

- 兼容微信将群聊搜索结果放在“最常使用/最近使用”分区的情况，精确群名仍可命中。
- 群聊搜索优先使用 `LegacyIAccessiblePattern.DoDefaultAction`，修复 `InvokePattern` 只关闭搜索结果但未切换会话的问题。
- 增加会话切换短轮询，等待群聊输入框真正切换完成后再确认发送。
## 2026-08-22

### 修复 Persona 提示词身份冲突

- 移除基础私聊/通用提示词中的硬编码“七七”身份，避免覆盖聊天记录生成的目标人物身份。
- Persona 注入调整到用户自定义提示词之后，确保选中的人物提示词在运行时生效。
- 保留无 Persona 时的“七七”默认助手身份，仅在未生成目标人物画像时使用。

## 2026-08-22

### 新增 Windows UIA 发送模式

- 新增 `backend/app/core/sender_windows_uia.py`，接入 `wechatauto-replica` 的微信 4.x UI Automation 驱动。
- Windows 发送器新增 `windows_sender.method`：
  - `uia`：通过 UIA 控件搜索会话、填充输入框并发送，不移动真实鼠标。
  - `mouse`：继续使用原有 `pyautogui` 坐标发送流程。
- 新增 `windows_sender.allow_mouse_fallback`：UIA 失败时是否允许回退到鼠标发送，默认配置为 `false`。
- UIA 驱动按现有密钥提取器绑定的微信进程筛选窗口，避免多账号时发送到错误账号。
- 群聊 UIA 搜索会限定“群聊”分区，降低同名联系人误命中的风险。
- 增加 UIA 发送依赖：`wechatauto-replica>=1.1.6.3`。

### 使用说明

```yaml
windows_sender:
  method: uia
  allow_mouse_fallback: false
```

如果 UIA 在当前微信版本或系统权限下不可用，日志会明确记录失败原因，不会自动移动鼠标。需要保证微信已登录且桌面未锁屏；如需保留旧版兼容发送，可将 `allow_mouse_fallback` 改为 `true`。

### 已知限制

- 当前微信 4.1.12.26 的部分界面使用自绘控件，UIA 需要微信进程可访问且 Qt accessibility gate 能成功激活；该步骤只激活无障碍状态位，不注入业务代码。
- 本次接入完成了代码和配置切换；最终能否在本机发送，需要在微信窗口实际运行时做一次端到端验证。

## 2026-08-22

### Windows UIA 改为后台优先发送

- 新增 `windows_sender.background_mode`，默认启用后台 UIA 路径，不调用 `ensure_window()`，避免微信窗口被激活到前台。
- 输入框在后台模式使用 UIA `LegacyIAccessiblePattern.SetValue()`；发送阶段向微信主窗口投递 Enter 消息，不移动鼠标、不聚焦窗口、不模拟真实键盘输入。
- 后台模式优先直接调用微信当前可见会话列表项，避免使用会触发微信前台化的搜索框 `ValuePattern`。
- 后台 UIA 找不到控件时直接失败，不自动切换到鼠标发送，保持 `allow_mouse_fallback: false`。
- 后台模式自动关闭发送后“停靠到小号”，避免额外切换会话抢占前台；即使配置残留为 `true` 也会被忽略。
- 发送完成后检查输入框是否清空；未清空时判定发送失败，避免出现日志显示成功但微信实际没有发出的情况。
- 新增 UIA 后台路径单测，并验证会话切换前后前台窗口句柄保持不变。
