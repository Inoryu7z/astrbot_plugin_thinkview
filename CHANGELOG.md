# Changelog

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
