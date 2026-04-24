import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register


@dataclass
class ToolCallEntry:
    tool_name: str = ""
    args_summary: str = ""
    result_summary: str = ""


@dataclass
class ThinkRecord:
    interaction_id: float = 0.0
    session: str = ""
    timestamp: float = 0.0
    user_message: str = ""
    reply_summary: str = ""
    reasoning_content: str = ""
    tool_calls: list = field(default_factory=list)
    has_thinking: bool = False
    confirmed: bool = False


@register("astrbot_plugin_thinkview", "Inoryu7z", "查看 bot 的思考记录，支持中转群配置", "1.0.0")
class ThinkViewPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self.config = config
        self.basic_conf = self.config.get("basic_conf", {})
        self.relay_conf = self.config.get("relay_conf", {})
        self.display_conf = self.config.get("display_conf", {})

        max_records = self.basic_conf.get("max_records", 50)
        self._records: dict[str, deque[ThinkRecord]] = {}
        self._max_records = max(10, max_records)

        self._pending: dict[float, ThinkRecord] = {}
        self._pending_tools: dict[float, list[ToolCallEntry]] = {}

    def _get_session_records(self, session: str) -> deque[ThinkRecord]:
        if session not in self._records:
            self._records[session] = deque(maxlen=self._max_records)
        return self._records[session]

    def _get_or_create_pending(self, interaction_id: float, session: str) -> ThinkRecord:
        if interaction_id not in self._pending:
            self._pending[interaction_id] = ThinkRecord(
                interaction_id=interaction_id,
                session=session,
                timestamp=time.time(),
            )
        return self._pending[interaction_id]

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        interaction_id = event.created_at
        session = event.unified_msg_origin

        record = self._get_or_create_pending(interaction_id, session)
        record.user_message = event.message_str[:200] if event.message_str else ""
        record.session = session

        if response.reasoning_content:
            if record.reasoning_content:
                record.reasoning_content += "\n---\n" + response.reasoning_content
            else:
                record.reasoning_content = response.reasoning_content
            record.has_thinking = True

        if not record.has_thinking:
            record.has_thinking = False

        record_level = self.basic_conf.get("record_level", "reasoning_only")
        if record_level in ("reasoning_and_tools", "full_agent_loop"):
            if interaction_id not in self._pending_tools:
                self._pending_tools[interaction_id] = []

    @filter.on_using_llm_tool()
    async def on_using_llm_tool(self, event: AstrMessageEvent, tool, tool_args):
        record_level = self.basic_conf.get("record_level", "reasoning_only")
        if record_level not in ("reasoning_and_tools", "full_agent_loop"):
            return

        interaction_id = event.created_at
        if interaction_id not in self._pending_tools:
            self._pending_tools[interaction_id] = []

        args_str = str(tool_args)
        args_summary = args_str[:100] + "..." if len(args_str) > 100 else args_str

        tool_name = getattr(tool, "name", str(tool))

        entry = ToolCallEntry(
            tool_name=tool_name,
            args_summary=args_summary,
        )
        self._pending_tools[interaction_id].append(entry)

    @filter.on_llm_tool_respond()
    async def on_llm_tool_respond(self, event: AstrMessageEvent, tool, tool_args, tool_result):
        record_level = self.basic_conf.get("record_level", "reasoning_only")
        if record_level not in ("reasoning_and_tools", "full_agent_loop"):
            return

        interaction_id = event.created_at
        if interaction_id not in self._pending_tools:
            return

        result_str = str(tool_result)
        result_summary = result_str[:150] + "..." if len(result_str) > 150 else result_str

        tool_name = getattr(tool, "name", str(tool))
        for entry in reversed(self._pending_tools[interaction_id]):
            if entry.tool_name == tool_name and not entry.result_summary:
                entry.result_summary = result_summary
                break

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        interaction_id = event.created_at
        if interaction_id not in self._pending:
            return

        record = self._pending.pop(interaction_id)
        record.confirmed = True

        result = event.get_result()
        if result and result.chain:
            reply_text = ""
            for comp in result.chain:
                if isinstance(comp, Plain):
                    reply_text += comp.text
            record.reply_summary = reply_text[:200] if reply_text else ""

        if interaction_id in self._pending_tools:
            record.tool_calls = self._pending_tools.pop(interaction_id)

        session_records = self._get_session_records(record.session)
        session_records.append(record)

        relay_session = self.relay_conf.get("relay_session", "")
        auto_relay = self.relay_conf.get("auto_relay", False)

        if relay_session and auto_relay:
            await self._relay_think_record(record)

    @filter.command("think", alias={"思考"})
    async def think_command(self, event: AstrMessageEvent, n: int = 1):
        if n < 1:
            n = 1

        is_admin = event.is_admin()

        if is_admin:
            all_records = []
            for session_records in self._records.values():
                all_records.extend(session_records)
            all_records.sort(key=lambda r: r.timestamp, reverse=True)
            records = all_records[:n]
        else:
            session = event.unified_msg_origin
            session_records = self._get_session_records(session)
            records = list(session_records)[-n:] if n <= len(session_records) else list(session_records)

        if not records:
            yield event.plain_result("暂无思考记录。")
            return

        relay_session = self.relay_conf.get("relay_session", "")
        output_parts = []
        for i, record in enumerate(reversed(records)):
            idx = len(records) - i
            output_parts.append(self._format_record(record, idx))

        output = "\n\n".join(output_parts)

        if relay_session:
            await self._relay_to_group(relay_session, output)
            yield event.plain_result(f"思考记录已发送到中转群。")
        else:
            if len(output) > 4000:
                output = output[:3900] + "\n\n... (内容过长已截断)"
            yield event.plain_result(output)

    def _format_record(self, record: ThinkRecord, idx: int = 1) -> str:
        parts = [f"🤔 思考记录 #{idx}"]

        if self.display_conf.get("show_timestamp", True) and record.timestamp:
            dt = datetime.fromtimestamp(record.timestamp)
            parts.append(f"📅 {dt.strftime('%Y-%m-%d %H:%M:%S')}")

        if self.display_conf.get("show_session_source", True) and record.session:
            source = self._format_session_source(record.session)
            parts.append(f"📍 {source}")

        if self.display_conf.get("show_user_message", True) and record.user_message:
            parts.append(f"💬 用户: {record.user_message}")

        if self.display_conf.get("show_reply_summary", True) and record.reply_summary:
            parts.append(f"🤖 回复: {record.reply_summary}")

        if record.has_thinking and record.reasoning_content:
            parts.append(f"\n🧠 思考过程:\n{record.reasoning_content}")
        else:
            parts.append("\n🧠 思考过程: (无思考内容)")

        if record.tool_calls:
            tool_parts = []
            for tc in record.tool_calls:
                if isinstance(tc, ToolCallEntry):
                    line = f"🔧 {tc.tool_name}({tc.args_summary})"
                    if tc.result_summary:
                        line += f" → {tc.result_summary}"
                    tool_parts.append(line)
            if tool_parts:
                parts.append("\n" + "\n".join(tool_parts))

        return "\n".join(parts)

    def _format_session_source(self, session: str) -> str:
        try:
            parts = session.split(":", 2)
            if len(parts) >= 3:
                platform = parts[0]
                msg_type = parts[1]
                session_id = parts[2]
                type_label = "群聊" if "Group" in msg_type else "私聊"
                return f"{platform} {type_label} {session_id}"
            return session
        except Exception:
            return session

    async def _relay_think_record(self, record: ThinkRecord):
        relay_session = self.relay_conf.get("relay_session", "")
        if not relay_session:
            return

        include_source = self.relay_conf.get("relay_include_source", True)

        if include_source:
            source = self._format_session_source(record.session)
            header = f"📡 来自 {source}"
            if record.user_message:
                header += f"\n💬 用户: {record.user_message}"
            output = header + "\n\n"
        else:
            output = ""

        if record.has_thinking and record.reasoning_content:
            output += f"🧠 思考过程:\n{record.reasoning_content}"
        else:
            output += "🧠 思考过程: (无思考内容)"

        if record.tool_calls:
            tool_parts = []
            for tc in record.tool_calls:
                if isinstance(tc, ToolCallEntry):
                    line = f"🔧 {tc.tool_name}({tc.args_summary})"
                    if tc.result_summary:
                        line += f" → {tc.result_summary}"
                    tool_parts.append(line)
            if tool_parts:
                output += "\n" + "\n".join(tool_parts)

        await self._relay_to_group(relay_session, output)

    async def _relay_to_group(self, session_str: str, text: str):
        try:
            chain = MessageChain([Plain(text)])
            success = await self.context.send_message(session_str, chain)
            if not success:
                logger.warning(f"[ThinkView] 中转群发送失败，session: {session_str}")
        except Exception as e:
            logger.error(f"[ThinkView] 中转群发送异常: {e}")
