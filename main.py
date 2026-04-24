import json
import os
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, MessageChain, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register

_TRUNC_USER_MSG = 200
_TRUNC_ARGS = 100
_TRUNC_RESULT = 150
_TRUNC_REPLY = 200
_TRUNC_OUTPUT = 4000
_MAX_QUERY_N = 20
_PENDING_TTL = 300
_PENDING_CLEANUP_THRESHOLD = 50
_COOLDOWN_SECONDS = 10
_PERSIST_FILE = "think_records.json"


@dataclass
class ToolCallEntry:
    tool_name: str = ""
    args_summary: str = ""
    result_summary: str = ""
    result_matched: bool = False

    def to_dict(self) -> dict:
        return {
            "tool_name": self.tool_name,
            "args_summary": self.args_summary,
            "result_summary": self.result_summary,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ToolCallEntry":
        return cls(
            tool_name=d.get("tool_name", ""),
            args_summary=d.get("args_summary", ""),
            result_summary=d.get("result_summary", ""),
        )


@dataclass
class ThinkRecord:
    interaction_id: str = ""
    session: str = ""
    timestamp: float = 0.0
    user_message: str = ""
    reply_summary: str = ""
    reasoning_content: str = ""
    tool_calls: list[ToolCallEntry] = field(default_factory=list)
    has_thinking: bool = False
    confirmed: bool = False

    def to_dict(self) -> dict:
        return {
            "interaction_id": self.interaction_id,
            "session": self.session,
            "timestamp": self.timestamp,
            "user_message": self.user_message,
            "reply_summary": self.reply_summary,
            "reasoning_content": self.reasoning_content,
            "tool_calls": [tc.to_dict() for tc in self.tool_calls],
            "has_thinking": self.has_thinking,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ThinkRecord":
        return cls(
            interaction_id=d.get("interaction_id", ""),
            session=d.get("session", ""),
            timestamp=d.get("timestamp", 0.0),
            user_message=d.get("user_message", ""),
            reply_summary=d.get("reply_summary", ""),
            reasoning_content=d.get("reasoning_content", ""),
            tool_calls=[ToolCallEntry.from_dict(tc) for tc in d.get("tool_calls", [])],
            has_thinking=d.get("has_thinking", False),
            confirmed=True,
        )


@register(
    "astrbot_plugin_thinkview",
    "Inoryu7z",
    "查看 bot 的思考记录，支持中转群配置",
    "1.3.0",
    repo="https://github.com/Inoryu7z/astrbot_plugin_thinkview",
)
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

        self._pending: dict[str, ThinkRecord] = {}
        self._pending_tools: dict[str, list[ToolCallEntry]] = {}
        self._pending_timestamps: dict[str, float] = {}

        self._cooldowns: dict[str, float] = {}

        self._persist_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), _PERSIST_FILE
        )
        self._load_records()

    @property
    def _record_level(self) -> str:
        return self.basic_conf.get("record_level", "reasoning_only")

    @property
    def _should_record_tools(self) -> bool:
        return self._record_level in ("reasoning_and_tools", "full_agent_loop")

    @property
    def _should_record_all(self) -> bool:
        return self._record_level == "full_agent_loop"

    @staticmethod
    def _make_interaction_id(event: AstrMessageEvent) -> str:
        existing = event.get_extra("thinkview_iid")
        if existing:
            return existing
        iid = f"{event.created_at}:{uuid.uuid4().hex[:8]}"
        event.set_extra("thinkview_iid", iid)
        return iid

    def _get_session_records(self, session: str) -> deque[ThinkRecord]:
        if session not in self._records:
            self._records[session] = deque(maxlen=self._max_records)
        return self._records[session]

    def _get_or_create_pending(self, interaction_id: str, session: str) -> ThinkRecord:
        if interaction_id not in self._pending:
            self._pending[interaction_id] = ThinkRecord(
                interaction_id=interaction_id,
                session=session,
                timestamp=time.time(),
            )
            self._pending_timestamps[interaction_id] = time.time()
        return self._pending[interaction_id]

    def _cleanup_stale_pending(self):
        if len(self._pending) < _PENDING_CLEANUP_THRESHOLD:
            return
        now = time.time()
        stale_ids = [
            iid for iid, ts in self._pending_timestamps.items()
            if now - ts > _PENDING_TTL
        ]
        for iid in stale_ids:
            self._pending.pop(iid, None)
            self._pending_tools.pop(iid, None)
            self._pending_timestamps.pop(iid, None)
        if stale_ids:
            logger.debug(f"[ThinkView] 清理了 {len(stale_ids)} 条过期 pending 记录")

    def _load_records(self):
        try:
            if not os.path.exists(self._persist_path):
                return
            with open(self._persist_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            for session, records in data.items():
                dq = deque(maxlen=self._max_records)
                for rd in records:
                    dq.append(ThinkRecord.from_dict(rd))
                self._records[session] = dq
            total = sum(len(v) for v in self._records.values())
            logger.info(f"[ThinkView] 已加载 {total} 条历史记录")
        except Exception as e:
            logger.warning(f"[ThinkView] 加载持久化记录失败: {e}")

    def _save_records(self):
        try:
            data = {}
            for session, records in self._records.items():
                data[session] = [r.to_dict() for r in records]
            with open(self._persist_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"[ThinkView] 保存持久化记录失败: {e}")

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, response: LLMResponse):
        self._cleanup_stale_pending()

        interaction_id = self._make_interaction_id(event)
        session = event.unified_msg_origin

        record = self._get_or_create_pending(interaction_id, session)
        record.user_message = event.message_str[:_TRUNC_USER_MSG] if event.message_str else ""
        record.session = session

        if response.reasoning_content:
            if response.is_chunk:
                record.reasoning_content += response.reasoning_content
            elif record.reasoning_content:
                record.reasoning_content += "\n---\n" + response.reasoning_content
            else:
                record.reasoning_content = response.reasoning_content
            record.has_thinking = True

        if self._should_record_tools:
            if interaction_id not in self._pending_tools:
                self._pending_tools[interaction_id] = []

    @filter.on_using_llm_tool()
    async def on_using_llm_tool(self, event: AstrMessageEvent, tool: Any, tool_args: Any):
        if not self._should_record_tools:
            return

        interaction_id = self._make_interaction_id(event)
        if interaction_id not in self._pending_tools:
            self._pending_tools[interaction_id] = []

        args_str = str(tool_args)
        args_summary = args_str[:_TRUNC_ARGS] + "..." if len(args_str) > _TRUNC_ARGS else args_str

        tool_name = getattr(tool, "name", str(tool))

        entry = ToolCallEntry(
            tool_name=tool_name,
            args_summary=args_summary,
        )
        self._pending_tools[interaction_id].append(entry)

    @filter.on_llm_tool_respond()
    async def on_llm_tool_respond(self, event: AstrMessageEvent, tool: Any, tool_args: Any, tool_result: Any):
        if not self._should_record_tools:
            return

        interaction_id = self._make_interaction_id(event)
        if interaction_id not in self._pending_tools:
            return

        result_str = str(tool_result)
        result_summary = result_str[:_TRUNC_RESULT] + "..." if len(result_str) > _TRUNC_RESULT else result_str

        tool_name = getattr(tool, "name", str(tool))
        for entry in self._pending_tools[interaction_id]:
            if entry.tool_name == tool_name and not entry.result_matched:
                entry.result_summary = result_summary
                entry.result_matched = True
                break

    @filter.after_message_sent()
    async def after_message_sent(self, event: AstrMessageEvent):
        interaction_id = self._make_interaction_id(event)
        if interaction_id not in self._pending:
            return

        record = self._pending.pop(interaction_id)
        self._pending_timestamps.pop(interaction_id, None)

        should_keep = False
        if self._should_record_all:
            should_keep = True
        elif self._should_record_tools and (record.has_thinking or interaction_id in self._pending_tools):
            should_keep = True
        elif record.has_thinking:
            should_keep = True

        if not should_keep:
            self._pending_tools.pop(interaction_id, None)
            return

        record.confirmed = True

        result = event.get_result()
        if result and result.chain:
            reply_text = "".join(
                comp.text for comp in result.chain if isinstance(comp, Plain)
            )
            record.reply_summary = reply_text[:_TRUNC_REPLY] if reply_text else ""

        if interaction_id in self._pending_tools:
            record.tool_calls = self._pending_tools.pop(interaction_id)

        session_records = self._get_session_records(record.session)
        session_records.append(record)

        self._save_records()

        relay_session = self.relay_conf.get("relay_session", "")
        auto_relay = self.relay_conf.get("auto_relay", False)

        if relay_session and auto_relay:
            await self._relay_think_record(record)

    def _check_cooldown(self, session: str) -> int:
        now = time.time()
        last_call = self._cooldowns.get(session, 0)
        remaining = int(_COOLDOWN_SECONDS - (now - last_call))
        if remaining > 0:
            return remaining
        self._cooldowns[session] = now
        return 0

    @filter.command("think", alias={"思考"})
    async def think_command(self, event: AstrMessageEvent, n: int = 1):
        remaining = self._check_cooldown(event.unified_msg_origin)
        if remaining > 0:
            yield event.plain_result(f"命令冷却中，请 {remaining} 秒后再试。")
            return

        n = max(1, min(n, _MAX_QUERY_N))
        is_admin = event.is_admin()

        if is_admin:
            all_records = []
            for session_records in self._records.values():
                all_records.extend(session_records)
            all_records.sort(key=lambda r: r.timestamp, reverse=True)
            records = all_records[:n]
        else:
            session_records = self._get_session_records(event.unified_msg_origin)
            records = list(session_records)[-n:]

        if not records:
            yield event.plain_result("暂无思考记录。")
            return

        output_parts = []
        for i, record in enumerate(reversed(records)):
            idx = len(records) - i
            output_parts.append(self._format_record(record, idx, sanitize=not is_admin))

        output = "\n\n".join(output_parts)

        force_local = self.display_conf.get("force_local_output", False)
        relay_session = self.relay_conf.get("relay_session", "")

        if relay_session and not force_local:
            await self._relay_to_group(relay_session, output)
            yield event.plain_result("思考记录已发送到中转群。")
        else:
            if len(output) > _TRUNC_OUTPUT:
                output = output[:_TRUNC_OUTPUT - 100] + "\n\n... (内容过长已截断)"
            yield event.plain_result(output)

    @filter.command("think_here", alias={"思考这里"})
    async def think_here_command(self, event: AstrMessageEvent, n: int = 1):
        remaining = self._check_cooldown(event.unified_msg_origin)
        if remaining > 0:
            yield event.plain_result(f"命令冷却中，请 {remaining} 秒后再试。")
            return

        n = max(1, min(n, _MAX_QUERY_N))
        is_admin = event.is_admin()

        if is_admin:
            all_records = []
            for session_records in self._records.values():
                all_records.extend(session_records)
            all_records.sort(key=lambda r: r.timestamp, reverse=True)
            records = all_records[:n]
        else:
            session_records = self._get_session_records(event.unified_msg_origin)
            records = list(session_records)[-n:]

        if not records:
            yield event.plain_result("暂无思考记录。")
            return

        output_parts = []
        for i, record in enumerate(reversed(records)):
            idx = len(records) - i
            output_parts.append(self._format_record(record, idx, sanitize=not is_admin))

        output = "\n\n".join(output_parts)
        if len(output) > _TRUNC_OUTPUT:
            output = output[:_TRUNC_OUTPUT - 100] + "\n\n... (内容过长已截断)"
        yield event.plain_result(output)

    @filter.command("think_clear", alias={"清除思考"})
    async def think_clear_command(self, event: AstrMessageEvent):
        is_admin = event.is_admin()

        if is_admin:
            count = sum(len(v) for v in self._records.values())
            self._records.clear()
        else:
            session = event.unified_msg_origin
            session_records = self._get_session_records(session)
            count = len(session_records)
            session_records.clear()

        self._save_records()
        scope = "所有会话" if is_admin else "当前会话"
        yield event.plain_result(f"已清除{scope}的 {count} 条思考记录。")

    @filter.command("think_search", alias={"搜索思考"})
    async def think_search_command(self, event: AstrMessageEvent, keyword: str = ""):
        if not keyword:
            yield event.plain_result("请提供搜索关键词，如: /think_search 关键词")
            return

        remaining = self._check_cooldown(event.unified_msg_origin)
        if remaining > 0:
            yield event.plain_result(f"命令冷却中，请 {remaining} 秒后再试。")
            return

        is_admin = event.is_admin()
        keyword_lower = keyword.lower()

        if is_admin:
            all_records = []
            for session_records in self._records.values():
                all_records.extend(session_records)
            all_records.sort(key=lambda r: r.timestamp, reverse=True)
            source_records = all_records
        else:
            session_records = self._get_session_records(event.unified_msg_origin)
            source_records = list(session_records)

        matched = [
            r for r in source_records
            if keyword_lower in r.user_message.lower()
            or keyword_lower in r.reasoning_content.lower()
            or keyword_lower in r.reply_summary.lower()
        ][:_MAX_QUERY_N]

        if not matched:
            yield event.plain_result(f"未找到包含「{keyword}」的思考记录。")
            return

        output_parts = []
        for i, record in enumerate(reversed(matched), 1):
            output_parts.append(self._format_record(record, i, sanitize=not is_admin))

        output = "\n\n".join(output_parts)

        force_local = self.display_conf.get("force_local_output", False)
        relay_session = self.relay_conf.get("relay_session", "")

        if relay_session and not force_local:
            await self._relay_to_group(relay_session, output)
            yield event.plain_result("搜索结果已发送到中转群。")
        else:
            if len(output) > _TRUNC_OUTPUT:
                output = output[:_TRUNC_OUTPUT - 100] + "\n\n... (内容过长已截断)"
            yield event.plain_result(output)

    @staticmethod
    def _validate_session_format(session_str: str) -> bool:
        if not session_str:
            return False
        parts = session_str.split(":", 2)
        if len(parts) != 3:
            return False
        if not parts[0] or not parts[1] or not parts[2]:
            return False
        return True

    @staticmethod
    def _sanitize_message(msg: str) -> str:
        if not msg:
            return ""
        if len(msg) <= 6:
            return msg[:2] + "***"
        return msg[:3] + "***" + msg[-3:]

    @staticmethod
    def _format_tool_calls(tool_calls: list[ToolCallEntry]) -> str:
        lines = []
        for tc in tool_calls:
            line = f"🔧 {tc.tool_name}({tc.args_summary})"
            if tc.result_summary:
                line += f" → {tc.result_summary}"
            lines.append(line)
        return "\n".join(lines)

    def _format_record(self, record: ThinkRecord, idx: int = 1, sanitize: bool = False) -> str:
        parts = [f"🤔 思考记录 #{idx}"]

        if self.display_conf.get("show_timestamp", True) and record.timestamp:
            dt = datetime.fromtimestamp(record.timestamp)
            parts.append(f"📅 {dt.strftime('%Y-%m-%d %H:%M:%S')}")

        if self.display_conf.get("show_session_source", True) and record.session:
            source = self._format_session_source(record.session)
            parts.append(f"📍 {source}")

        if self.display_conf.get("show_user_message", True) and record.user_message:
            display_msg = self._sanitize_message(record.user_message) if sanitize else record.user_message
            parts.append(f"💬 用户: {display_msg}")

        if self.display_conf.get("show_reply_summary", True) and record.reply_summary:
            parts.append(f"🤖 回复: {record.reply_summary}")

        if record.has_thinking and record.reasoning_content:
            parts.append(f"\n🧠 思考过程:\n{record.reasoning_content}")

        if record.tool_calls:
            tool_text = self._format_tool_calls(record.tool_calls)
            if tool_text:
                parts.append("\n" + tool_text)

        return "\n".join(parts)

    @staticmethod
    def _format_session_source(session: str) -> str:
        try:
            parts = session.split(":", 2)
            if len(parts) >= 3:
                platform = parts[0]
                msg_type = parts[1]
                session_id = parts[2]
                type_label = "群聊" if "Group" in msg_type else "私聊"
                return f"{platform} {type_label} {session_id}"
            return session
        except (ValueError, IndexError):
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
                header += f"\n💬 用户: {self._sanitize_message(record.user_message)}"
            output = header + "\n\n"
        else:
            output = ""

        if record.has_thinking and record.reasoning_content:
            output += f"🧠 思考过程:\n{record.reasoning_content}"

        if record.tool_calls:
            tool_text = self._format_tool_calls(record.tool_calls)
            if tool_text:
                output += "\n" + tool_text

        if len(output) > _TRUNC_OUTPUT:
            output = output[:_TRUNC_OUTPUT - 100] + "\n\n... (内容过长已截断)"

        await self._relay_to_group(relay_session, output)

    async def _relay_to_group(self, session_str: str, text: str):
        if not self._validate_session_format(session_str):
            logger.warning(f"[ThinkView] 中转群 session 格式无效: {session_str}，期望格式: platform_id:MessageType:session_id")
            return
        try:
            chain = MessageChain([Plain(text)])
            success = await self.context.send_message(session_str, chain)
            if not success:
                logger.warning(f"[ThinkView] 中转群发送失败，session: {session_str}")
        except Exception as e:
            logger.error(f"[ThinkView] 中转群发送异常: {e}")
