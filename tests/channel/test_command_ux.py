"""User-facing command outcomes preserve the actual Agent terminal fact."""

from workflowweave.channel.base import BaseConversationChannel


class _Port:
    def __init__(self, *, turn=None, command=None):
        self.turn = turn
        self.command = command

    async def wait(self, _turn_id):
        return self.turn

    async def wait_command(self, _session_id, *, request_id=None, event_id=None):
        return self.command


async def test_compact_turn_and_command_outcomes_are_action_specific():
    idle = BaseConversationChannel(_Port(turn={"status": "completed", "text": ""}))
    assert (await idle.finish_turn("turn", operation="compact")).text == "上下文整理已完成。"

    queued = BaseConversationChannel(_Port(command={
        "type": "command.completed", "command": "compact", "compacted": False,
    }))
    outcome = await queued.finish_command("session", event_id=3)
    assert outcome.status == "completed"
    assert outcome.text == "当前上下文无需压缩。"


async def test_command_failure_keeps_public_error_code_and_message():
    channel = BaseConversationChannel(_Port(command={
        "type": "command.failed", "command": "append",
        "error": {"code": "context_compaction_failed", "message": "上下文整理失败"},
    }))
    outcome = await channel.finish_command("session", request_id="append")
    assert outcome.status == "failed"
    assert outcome.text == "补充内容处理失败：context_compaction_failed：上下文整理失败"
