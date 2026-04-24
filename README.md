[![ThinkView Counter](https://count.getloli.com/get/@Inoryu7z.thinkview?theme=miku)](https://github.com/Inoryu7z/astrbot_plugin_thinkview)

# 🧠 ThinkView · 思维透镜

查看 Bot 的思考记录，让推理过程不再黑盒。

**ThinkView** 是一个思考记录查看插件，它会自动捕获 LLM 的推理内容（reasoning_content）和工具调用过程，让你可以随时回看 Bot 在回复时到底想了什么。

---

## ✨ 它能做什么

### 🧠 自动记录思考过程

当 Bot 使用支持推理的模型（如 DeepSeek-R1）回复时，ThinkView 会自动捕获其推理内容并保存。

记录内容包括：
- 用户的原始消息摘要
- Bot 的推理/思考过程
- Bot 最终回复的摘要
- 时间戳与会话来源

### 🔧 工具调用追踪

可选记录 Bot 在回复过程中调用了哪些工具、传了什么参数、得到了什么结果。

支持两种记录层级：
- **reasoning_and_tools**：推理 + 工具调用摘要
- **full_agent_loop**：完整 Agent 循环记录

### 📡 中转群转发

支持将思考记录自动转发到指定的中转群，方便在独立频道集中查看 Bot 的思考过程。

### 👥 权限区分

- **普通用户**：只能查看自己所在会话的思考记录
- **管理员**：可以查看所有会话的思考记录

---

## 🎮 可用指令

| 指令 | 别名 | 权限 | 说明 |
|------|------|------|------|
| `/think` | `/思考` | 所有人 | 查看最近的思考记录，支持 `/think 3` 查看最近 3 条 |

---

## ⚙️ 主要配置项

### 基础配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `record_level` | 记录层级：`reasoning_only` / `reasoning_and_tools` / `full_agent_loop` | `reasoning_only` |
| `max_records` | 每个会话最大记录数 | `50` |

### 中转配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `relay_session` | 中转群 session 字符串，留空不启用 | — |
| `auto_relay` | 每次回复后自动转发到中转群 | `false` |
| `relay_include_source` | 中转消息附带来源上下文 | `true` |

### 展示配置

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `show_user_message` | 展示用户消息摘要 | `true` |
| `show_reply_summary` | 展示回复摘要 | `true` |
| `show_timestamp` | 展示时间戳 | `true` |
| `show_session_source` | 展示会话来源 | `true` |

---

## 📌 使用说明

1. 仅当模型返回了 `reasoning_content` 时才会记录思考过程。
2. `reasoning_only` 模式下，无思考内容的回复不会被记录。
3. `/think` 命令最多返回 20 条记录。
4. 中转群 session 格式示例：`aiocqhttp:GroupMessage:123456789`

---

## 📝 版本记录

详细更新见 `CHANGELOG.md`。
