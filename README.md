# Weix — 微信全 AI 自动回复机器人

接入大模型，让 AI 替你自动回微信。**不封号**。

## 核心原理

- **收消息**：直接读取微信本地 SQLite 数据库（纯文件 I/O，微信进程无感知）
- **AI 回复**：LangChain 编排大模型，支持多轮对话、工具调用、意图识别
- **发消息**：Windows 优先使用 UI Automation 控件调用，鼠标发送可配置为显式兜底；macOS 使用 AppleScript
  - Windows：`uia` 模式按账号绑定的微信 PID 获取 UIA 窗口，写入聊天输入框并调用真实发送按钮的 `InvokePattern` / `LegacyIAccessible.DoDefaultAction`；`mouse` 模式使用旧版 GUI 发送器
  - macOS：AppleScript 模拟键盘输入
- **可视化管理**：Vue3 Web 后台，配置 AI、规则、模板，开箱即用

## 功能

### 核心功能：全 AI 自动回复
- **智能对话**：接入 DeepSeek / OpenAI / 硅基流动等大模型，像真人一样聊天
- **多轮记忆**：记住上下文，长期记忆支持 90 天回溯
- **工具调用**：天气查询、地图导航、搜索、计算等，AI 自动调用工具
- **意图识别**：点单、投诉、咨询等意图自动触发对应工作流
- **人设定制**：自定义 System Prompt，设定回复风格和角色
- **本人 Skill**：从多个聊天 JSON 中按 `senderUsername` 选择目标人物，支持 AI 人格生成、历史话术复用和混合模仿

### 增强功能
- 关键词 / 正则规则兜底（AI 没匹配到时走规则）
- 工作流引擎（陪玩点单流程：填单 → 确认 → 转发接单群 → 分配）
- 消息模板（文本 / 卡片 / 表单 / 列表，支持变量替换）
- 转发规则（关键词 / 工作流事件触发，多目标群转发）
- 统计分析（发言排行 / 时段热力图 / TF-IDF 关键词 / AI 摘要）
- 定时任务（日报 / 周报 / 数据清理 / 健康检查）
- 防封号策略（频率控制 / 行为模拟 / 熔断保护）

## 系统架构

```
微信客户端 ──(只读)──▶ 数据库解密层 ──▶ 消息监听器 ──▶ AI Agent（核心）
                                                         │
                                               LangChain + 大模型
                                                         │
                                          ┌──────────────┼──────────────┐
                                          ▼              ▼              ▼
                                      规则引擎       工作流引擎      工具调用
                                          │              │              │
                                          └──────────────┼──────────────┘
                                                         ▼
                                                  消息发送层
                                              ┌─────────┴─────────┐
                                              ▼                   ▼
                                      Windows (UIA / 鼠标兜底)  macOS (AppleScript)
```

## 平台支持

| 维度 | Windows | macOS |
|------|---------|-------|
| 微信版本 | PC 微信 4.1.12.26（UIA）/ 3.9 系列（鼠标兼容模式） | Mac 微信 4.x (App Store) |
| DB 路径 | `Documents/WeChat Files/<wxid>/Msg/` | `~/Library/Containers/com.tencent.xinWeChat/...` |
| 密钥提取 | `ReadProcessMemory` (Win32 API) | `mach_vm_read_overwrite` (Mach VM) |
| 消息发送 | 后台 UIA 控件调用（可关闭鼠标兜底） | AppleScript 模拟键盘输入 |
| 发送风险 | UIA 控件调用和窗口消息投递；必要时激活微信 accessibility 状态位，不注入代码 | 极低（与真人操作无异） |
| 管理员权限 | 需要 | 需要 |

## 技术栈

- 后端：FastAPI + SQLAlchemy (async) + aiosqlite
- AI：LangChain 0.3+ + LangGraph
- 前端：Vue 3 + Element Plus + ECharts + Pinia
- 定时：APScheduler
- 数据库解密：pycryptodome (SQLCipher 4)

## 快速开始

### 1. 克隆项目

```bash
git clone <repo-url> weix
cd weix
```

### 2. 创建本地配置文件

```bash
# 复制配置模板
cp config/config.example.yaml config/config.yaml

# 复制环境变量模板
cp .env.example .env
```

然后编辑这两个文件，填入你的 API Key 等信息。

Windows UIA 生产环境默认使用后台优先策略：后台 UIA 先尝试，只有在尚未执行发送动作且达到后台尝试次数后，才按配置切换前台 UIA：

```yaml
windows_sender:
  method: uia
  send_mode: auto
  background_mode: false
  allow_foreground_activation: true
  background_post_message: true
  background_attempts: 1
  foreground_attempts: 1
  ensure_full_layout: true
  allow_mouse_fallback: false
  send_key_fallback: none
  # Weixin 4.x 按钮 Pattern 可能返回成功但不消费正文；显式聚焦真实按钮后触发其默认动作
  send_button_key_fallback: enter
  require_ui_verify: true
  verify_after_send: true
  pending_verify_retries: 2
  park_after_send: false
```

`auto` 默认先走 `background_uia`，后台失败次数由 `background_attempts` 控制；后台能力不足或次数耗尽后，只有 `allow_foreground_activation: true` 才会走 `foreground_uia`，前台次数由 `foreground_attempts` 控制。
每次重试都必须先证明上一轮没有执行发送动作；只要已经调用发送按钮、输入框已清空、消息状态不明确或后台改变了全局输入状态，就会立即停止，禁止换路径重复发送。系统永不回退鼠标物理点击。
`send_button_key_fallback` 是前台 UIA 对已找到的真实发送按钮执行默认动作，不是向聊天输入框盲发 Enter；`background_uia` 永不使用键盘兜底。
两条 UIA 路径都必须先通过所选账号的 PID 绑定校验。
当前微信版本的 `InvokePattern` 可能返回调用成功而不真正发送，因此不能单独作为成功依据。

发送结果分为三层确认：

1. `invoke`：发送按钮 Pattern 已被调用。
2. `ui_verify`：输入框已清空，并且消息列表发现本人发送的正文。
3. `db_verify`：目标会话的本地消息数据库发现同一正文。若微信落盘较慢，状态暂时为 `pending_verify`，
   后台只查库重试，不会重复调用 UIA 发送动作。

管理后台“聊天配置 → UIA 发送策略”可以配置后台/前台最大尝试次数、后台优先模式和失败后是否允许前台接管；“UIA 检测”可以查看 `binding_status`、选中账号、绑定账号、绑定 PID、驱动 PID、窗口 PID、
输入框、发送按钮和 `error_code`。常见绑定错误码包括 `ambiguous_process`、`account_binding_mismatch`、
`account_binding_unverified`、`window_pid_mismatch`；常见投递错误码包括 `target_id_required`、
`db_not_confirmed`、`uia_exception`。

### macOS

```bash
# 3. 环境初始化
bash scripts/setup.sh

# 4. 授予辅助功能权限
# 系统偏好设置 → 隐私与安全性 → 辅助功能 → 添加终端

# 5. 启动（首次提取密钥需 sudo）
sudo bash scripts/start.sh
```

### Windows

```cmd
REM 3. 环境初始化
scripts\setup.bat

REM 4. 以管理员权限启动
scripts\start.bat
```

首次运行会**自动**从本机微信进程内存中提取数据库解密密钥，保存到 `data/all_keys.json`。如果自动提取失败，可手动设置环境变量 `WEIX_WECHAT_DB_KEY`（64 位十六进制密钥）。

### Windows 一键发布包

在项目根目录运行 `scripts\build_backend.bat`，构建完成后将整个 `dist\Weix` 文件夹复制到目标电脑，双击其中的 `Weix.exe` 即可启动。也可以双击同目录的 `scripts\start_weix.bat`（如果已复制该脚本）。

打包启动器会自动启动后端、加载内置的前端管理页面，并打开浏览器访问 `http://127.0.0.1:8000`。首次运行会从内置模板创建 `config\config.yaml`，请先编辑该文件填写 API Key、管理员密码和微信账号相关配置；后续配置可在管理界面调整。打包版不使用开发服务器的 `http://127.0.0.1:5173`。

默认发布包不包含本机数据库、密钥和聊天记录。若只制作当前电脑使用的便携包，可在构建前执行 `set WEIX_BUNDLE_RUNTIME_DATA=1`，但不要把这种包分发给他人。

## 管理后台

访问 http://localhost:5173，默认用户名/密码在 `config/config.yaml` 中配置（从 `config/config.example.yaml` 复制后修改）。

- **仪表盘**：在线状态、消息数、活跃群聊、订单数
- **统计报告**：发言排行、时段分布、关键词、AI 摘要
- **消息日志**：历史消息查询与详情
- **聊天配置**：群聊白名单、私聊权限、回复模式
- **自动回复规则**：关键词/正则/意图规则管理
- **消息模板**：文本/卡片/表单/列表模板编辑器
- **工作流配置**：状态机定义（默认含陪玩点单流程）
- **转发规则**：触发条件 + 目标群配置
- **AI 配置**：Provider、API Key、模型、System Prompt
- **Embedding 配置**：可选择本地模型，或使用 DashScope / SiliconFlow / OpenAI 的云端向量模型
- **本人 Skill**：AI 分析你的聊天记录，自动生成你的语气人设、自我记忆、私聊/群聊 Prompt
- **历史聊天模仿**：`replay` 模式本地匹配“上下文 → 目标人物回复”，无需 API Key；`hybrid` 模式在历史复用和 Persona 生成之间回退
- **定时任务**：日报/周报/健康检查/数据清理管理
- **系统配置**：日志级别、数据保留、异常告警、备份恢复

## 配置文件

主配置 `config/config.yaml`（从 `config/config.example.yaml` 复制），关键配置项：

| 配置项 | 说明 |
|--------|------|
| `platform` | 运行平台 (auto / windows / macos) |
| `ai` | LLM 配置 (provider, api_key, model 等) |
| `ai.embedding` | 向量检索配置 (provider, api_key, base_url, model)；新配置默认使用 DashScope `text-embedding-v3` |
| `ai.persona_replay` | 历史话术复用阈值、上下文条数、few-shot 数量和重复冷却 |
| `auto_reply.rules` | 自动回复规则（关键词/正则/意图） |
| `templates` | 消息模板定义 |
| `workflows` | 工作流状态机定义 |
| `anti_detect` | 防检测参数（发送间隔/频率/熔断） |
| `admin` | 管理后台用户名/密码 |

`ai.embedding` 示例：

```yaml
ai:
  embedding:
    provider: dashscope
    model: text-embedding-v3
    base_url: https://dashscope.aliyuncs.com/compatible-mode/v1
    api_key: ${DASHSCOPE_API_KEY:-}
```

旧配置没有 `ai.embedding` 时仍使用已下载的本地模型。切换 Embedding 后，程序会按供应商和模型使用独立的 ChromaDB 目录；切换完成后建议重启一次后端，并重新导入或建立需要检索的知识内容。

## 目录结构

```
weix/
├── backend/
│   └── app/
│       ├── core/       # 平台自适应核心（密钥提取/DB读取/消息发送/监听/防检测）
│       ├── ai/         # LangChain AI 引擎（Agent/工具/提示词/记忆/模型）
│       ├── workflow/   # 工作流引擎（规则/模板/状态机/转发）
│       ├── api/        # REST API 路由
│       ├── services/   # 业务逻辑
│       ├── models/     # ORM 模型 + Pydantic schemas
│       └── utils/      # 工具（限流器/日志）
├── frontend/           # Vue3 管理前端
├── config/             # 配置文件
├── memory/             # 功能变化和实现约束记忆
├── scripts/            # 部署脚本
└── README.md
```

### 历史聊天模仿模式

在管理后台“本人 Skill”页面上传一个或多个聊天 JSON，系统使用消息内部的
`senderUsername` 识别人物，使用 `senderDisplayName` 展示名称；文件名只作为来源标记。
人物列表同时展示稳定 ID，多个 JSON 中相同 `senderUsername` 会合并为同一个人物。
选择人物后可切换：

- `AI 人格生成`：调用 LLM 生成 Persona、Self Memory 和新回复。
- `历史话术复用`：建立本地 `data/persona_replay.json` 索引，匹配相似上下文并复用历史原话；没有可靠匹配时不回复。
- `混合模仿（推荐）`：高相似度复用原话，中等相似度将历史样本作为表达参考，低相似度回退 Persona。

索引只处理文本消息，并按来源文件、会话和群聊/私聊场景隔离，不会把不同 JSON 文件首尾拼接。历史聊天内容始终作为数据处理，不会被提升为系统指令。阈值配置位于 `ai.persona_replay`，可在页面或配置文件中调整。
删除临时导入 JSON 后，已经生成的 `data/persona_replay.json` 索引会继续保留，直到清除 Persona。

## 防封号策略

1. **收消息零风险**：只读数据库文件，微信进程完全无感知
2. **发消息零注入**：Windows / macOS 均采用 GUI 模拟操作，不注入 DLL、不 Hook 进程，与真人操作无异
3. **频率控制**：全局每分钟 ≤ 20 条，单会话冷却 30s
4. **行为模拟**：发送间隔随机化（Win 15-45s / Mac 8-20s）
5. **熔断保护**：连续失败 3 次暂停 5 分钟

## License

MIT
