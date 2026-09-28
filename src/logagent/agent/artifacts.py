"""Save complete tool output before returning a bounded, explicitly partial preview."""

import hashlib
import json

from logagent.errors import LogAgentError
from logagent.redaction import redact_data

_RESULT_FIELDS = ("status", "count", "exit_code", "hash", "path", "kind", "offset", "next_offset",
                  "next_cursor", "total_lines", "readonly", "error", "saved_bytes")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class ArtifactStore:
    def __init__(self, workspace):
        self.workspace = workspace

    async def save(self, result, *, session_id, turn_id, tool_call_id,
                   config, count_tokens, schema_output=False, read_enabled=True, preserve_full=False):
        # This flag is owned by the gateway wrapper, not by arbitrary tool output.
        # Schema property names such as "token" are declarations, not credentials.
        safe = result if schema_output or preserve_full else redact_data(result)
        text = json_text(safe)
        content = json.dumps(safe, ensure_ascii=False, allow_nan=False, indent=2).encode("utf-8")
        exceeded = len(content) > config.output_bytes and not preserve_full
        key = hashlib.sha256(f"{turn_id}:{tool_call_id}".encode()).hexdigest()
        suffix = ".partial.txt" if exceeded else ".json"
        path = f"Artifacts/{session_id}/{key}{suffix}"
        saved = content if preserve_full else content[:config.output_bytes].decode("utf-8", errors="ignore").encode("utf-8")
        await self.workspace.save_runtime(path, saved)
        envelope = {key: safe[key] for key in _RESULT_FIELDS if key in safe}
        envelope.update(artifact_path=path, truncated=False)
        if exceeded:
            envelope.update(status="output_limit_exceeded", truncated=True,
                            saved_bytes=len(saved),
                            error={"code": "output_limit_exceeded", "message": "完整输出超过单次预算，已保留部分输出"})
            text = ""
        elif not schema_output and not preserve_full:
            page = self._page(safe, envelope, config.preview_tokens, count_tokens)
            if page is not None:
                return page
        envelope["preview"] = text
        if count_tokens(json_text(envelope)) <= config.preview_tokens:
            return envelope
        envelope["truncated"] = True
        if schema_output:
            envelope["preview"] = "Schema 已保存，请使用 read 分页读取 artifact_path"
            if not read_enabled:
                envelope.update(status="output_budget_exceeded", preview="",
                                error={"code": "output_budget_exceeded",
                                       "message": "Schema 超过预览预算且 read 已关闭；请启用 read 或提高预算"})
        else:
            if preserve_full and not read_enabled:
                raise LogAgentError("output_budget_exceeded", "完整 MCP 结果超过预览预算且 read 已关闭")
            low, high = 0, len(text)
            while low < high:
                middle = (low + high + 1) // 2
                envelope["preview"] = text[:middle]
                if count_tokens(json_text(envelope)) <= config.preview_tokens:
                    low = middle
                else:
                    high = middle - 1
            envelope["preview"] = text[:low]
        if count_tokens(json_text(envelope)) > config.preview_tokens:
            raise LogAgentError("preview_budget_exceeded", "工具结果引用与状态无法装入预览预算",
                                {"artifact_path": path})
        return envelope

    @staticmethod
    def _page(result, envelope, budget, count_tokens):
        field = next((name for name in ("entries", "matches") if name in result), None)
        if result.get("kind") == "file":
            field, items = "content", result["content"].splitlines(keepends=True)
        elif field is not None:
            items = result[field]
        else:
            return None
        def candidate_for(count):
            candidate = dict(envelope)
            candidate[field] = "".join(items[:count]) if field == "content" else items[:count]
            candidate["truncated"] = count < len(items) or result.get("truncated", False)
            if count < len(items):
                if result.get("kind") in {"file", "directory"}:
                    candidate["next_offset"] = result["offset"] + count
                elif field == "entries":
                    candidate["next_cursor"] = result["cursor"] + count
            return candidate

        low, high = 0, len(items)
        while low < high:
            middle = (low + high + 1) // 2
            if count_tokens(json_text(candidate_for(middle))) <= budget:
                low = middle
            else:
                high = middle - 1
        candidate = candidate_for(low)
        if items and low == 0:
            candidate.update(status="output_budget_exceeded",
                             error={"code": "output_budget_exceeded",
                                    "message": "单个条目超过预览预算，请提高预算或缩小读取范围"})
        if count_tokens(json_text(candidate)) > budget:
            raise LogAgentError("preview_budget_exceeded", "工具分页状态无法装入预览预算",
                                {"artifact_path": envelope["artifact_path"]})
        return candidate
