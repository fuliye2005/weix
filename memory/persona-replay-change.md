# 历史聊天模仿模式变更记忆

## 记录时间

2026-08-22

## 功能目标

在 Weix 现有的 AI Persona 人格生成能力之外，增加可选择的历史聊天模仿方式：

- `persona`：由 LLM 根据目标人物聊天记录生成 Persona、Self Memory 和运行时提示词。
- `replay`：根据历史“上下文 → 目标人物回复”样本进行本地话术复用，不依赖 API Key。
- `hybrid`：高相似度复用原话，中等相似度提供历史表达参考，低相似度回退 Persona。

## 身份和数据原则

- 使用 `senderUsername` 作为人物稳定 ID，`senderDisplayName` 作为展示名称。
- JSON 文件名仅作为来源标记，不作为人物身份判断依据。
- 多个 JSON 中相同 `senderUsername` 的消息应合并为同一个人物。
- 聊天文本只作为待处理数据，不能提升为系统指令。
- 第一版只处理文本消息，不处理图片、语音、文件和系统消息。
- 导入内容、人物提示词和历史复用索引均保存在本地。

## 技术边界

- 不修改微信数据库发送逻辑。
- 不启用鼠标发送或前台窗口操作。
- 不改变 Windows 后台 UIA 发送配置。
- 不向真实联系人发送测试消息。
- 不污染现有 LangGraph checkpoint、Persona 记忆和 RAG 流程。

## 计划中的本地索引

历史复用索引单独保存为：

```text
data/persona_replay.json
```

索引样本包含场景、来源文件、上下文、目标人物 ID、历史回复和出现次数，避免把大量原始记录写入 `persona_skill.json`。

## 计划中的匹配策略

使用纯本地中文字符 bigram/trigram、词项重合度、上下文组合得分和场景权重计算 `0～1` 的相似度。默认阈值：

```yaml
persona_replay:
  direct_threshold: 0.82
  few_shot_threshold: 0.55
  context_messages: 3
  few_shot_count: 3
  repeat_cooldown: 20
```

低于阈值时不强行随机回复，并对同一会话的历史回复做冷却和去重。

## 实现状态

- [x] 建立功能记忆文档
- [x] 扩展聊天记录规范化字段
- [x] 新增历史上下文—回复索引与匹配引擎
- [x] 接入 `persona`、`replay`、`hybrid` 运行时策略
- [x] 增加 API 和 Persona 管理界面选项
- [x] 补充后端测试、前端构建检查、README 和 CHANGELOG
- [x] 继承顶层会话元数据并缓存目标人物稳定 ID
- [x] replay 运行时只读加载缓存，不初始化 LLM
- [x] replay 管理接口的读取、编辑和清理路径不初始化 LLM
- [x] 过滤撤回提示和常见系统/媒体消息
- [x] 清除 Persona 时同步失效内存中的 replay 引擎

## 已实现的文件

- `backend/app/ai/chat_import.py`：保留来源、顺序、会话和场景元数据。
- `backend/app/ai/persona_replay.py`：本地索引、匹配、few-shot 格式化和冷却。
- `backend/app/ai/style_distiller.py`：兼容旧缓存，支持 replay Skill 和 simulation mode。
- `backend/app/ai/agent.py`：运行时分流并保持 Persona、RAG、记忆和 checkpoint 链路。
- `backend/app/api/persona.py`：导入分析、模式选择、索引统计和清理。
- `frontend/src/components/PersonaSkillPanel.vue`：模式选择和历史匹配参数配置。

## 验证记录

- 两组本地匿名聊天 JSON 只读解析成功：共 51,938 条文本消息，目标人物可生成 7,392 组上下文—回复样本。
- 后端专项测试：30 passed，包含聊天导入、Persona API、Persona 缓存和 replay 运行时策略。
- 前端 `npm run build`：通过。
- `python -m compileall -q app tests`：通过。
- `git diff --check`：通过。
- 两组本地匿名 JSON 只读验证：51,938 条文本消息、6 位参与者；目标人物包含 11,374 条消息，建立 7,392 组历史样本并成功命中原话。
- 完整后端套件：95 passed；剩余 10 failed、12 errors 来自既有 Windows sender、OCR、临时清理和集成测试环境/平台依赖，不涉及本功能专项测试。
