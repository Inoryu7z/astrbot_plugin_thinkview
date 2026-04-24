# Changelog

## 1.2.0 — 2026-04-24

### 🐛 Bug 修复
- 🔧 修复流式模式下 `reasoning_content` 被 `\n---\n` 分隔符污染的问题（chunk 直接拼接，非 chunk 多轮推理用分隔符）
- 🔧 修复 `full_agent_loop` 记录层级与 `reasoning_and_tools` 行为无区别的问题（新增 `_should_record_all` 属性，三级明确区分）
- 🔧 简化非管理员查询记录时的冗余条件判断
- 🔧 `_format_session_source` 异常捕获从 `except Exception` 收窄为 `except (ValueError, IndexError)`

### ✨ 新功能
- 🆕 新增 `/think_clear`（别名 `/清除思考`）命令，支持清除思考记录
- 🆕 新增 `/think_search`（别名 `/搜索思考`）命令，支持按关键词搜索记录
- 🆕 新增持久化存储，记录保存到 `think_records.json`，重启不丢失
- 🆕 新增命令冷却机制（10 秒/会话），防止高频调用
- 🆕 新增用户消息脱敏处理，非管理员查看时中间内容用 `***` 替代

### 🧹 改进
- 🧹 pending 清理策略优化：数量低于阈值（50）时跳过清理，避免每次 LLM 响应都遍历
- 🧹 `interaction_id` 改用 `uuid4` 生成，通过 `event.get_extra/set_extra` 缓存保证一致性
- 🧹 `@register` 装饰器新增 `repo` 参数
- 🧹 `tool`/`tool_args`/`tool_result` 参数添加 `Any` 类型注解
- 🧹 `_conf_schema.json` 中 `"type": "int"` 修正为 `"type": "integer"`
- 🧹 新增 `.gitignore` 排除运行时数据文件

## 1.1.0 — 2026-04-24

### 🐛 Bug 修复
- 🔧 修复 `interaction_id` 使用 float 时间戳导致同一秒多事件碰撞的问题（改为 `timestamp:event_id` 组合键）
- 🔧 修复同名工具连续调用时结果匹配到错误条目的问题（改用 `result_matched` 标记替代 `reversed + not result_summary`）
- 🔧 修复 `reasoning_only` 模式下无思考内容的记录仍被存入内存的问题

### ✨ 改进
- 🧹 移除"🧠 思考过程: (无思考内容)"的无意义展示
- 🧹 添加 pending 记录自动清理机制（TTL 300 秒），防止内存泄漏
- 🧹 提取 `_record_level` / `_should_record_tools` 属性缓存配置读取
- 🧹 循环字符串拼接改为 `"".join()`
- 🧹 移除未使用的 `Optional` 导入和冗余代码
- 🧹 `tool_calls` 类型注解从 `list` 改为 `list[ToolCallEntry]`
- 🧹 魔法数字提取为模块级常量
- 🧹 工具格式化逻辑提取为 `_format_tool_calls()` 静态方法，消除重复代码
- 🔒 `/think` 命令 `n` 参数添加上限 20，防止查询过多记录
- 🔒 中转群消息添加长度截断

## 1.0.0 — 2026-04-23

### 🎉 初始版本
- 查看 bot 的思考记录
- 支持中转群配置
- 支持管理员/普通用户权限区分
