"""Build independent input views; every hard limit uses all consuming tokenizers."""
from copy import deepcopy
from dataclasses import dataclass

from workflowweave.errors import WorkFLowWeaveError
from workflowweave.models import InputView
from workflowweave.workflow.input_formats import equal_json, json_text, serialize, strict_json


@dataclass(frozen=True)
class Part:
    structured: bool
    value: object
    original: str | None = None


def extract(raw, kind):
    if raw is None:
        raise WorkFLowWeaveError("raw_unavailable", "原始获取结果不可用，不能隐式重新采集")
    if kind in {"cli", "file"}:
        text = raw["stdout"] if kind == "cli" else raw["text"]
        valid, value = strict_json(text)
        return [Part(valid, value if valid else text, text)]
    structured = "structuredContent" in raw
    value = raw.get("structuredContent")
    parts, original = [], None
    for block in raw.get("content", []):
        if block.get("type") == "resource":
            resource = block.get("resource")
            if (isinstance(resource, dict) and isinstance(resource.get("uri"), str)
                    and isinstance(resource.get("text"), str)):
                text = f"[resource={resource['uri']}]\n{resource['text']}"
                parts.append(Part(False, text, text))
                continue
        if block.get("type") != "text":
            raise WorkFLowWeaveError("input_content_unsupported", "Workflow 文本输入不支持此 MCP 内容块",
                                {"type": block.get("type")})
        text = block["text"]
        valid, parsed = strict_json(text)
        if structured and valid and equal_json(value, parsed):
            if original is None:
                original = text
            continue
        parts.append(Part(valid, parsed if valid else text, text))
    if structured:
        parts.insert(0, Part(True, deepcopy(value), original))
    return parts


def fits(text, limit, counters):
    return limit is None or all(counter(text) <= limit for counter in counters)


def prefix(text, predicate):
    # Tokenizer counts are treated as monotone for prefix growth. Every selected
    # candidate is still checked by the predicate before it is returned.
    low, high, best = 0, len(text), None
    while low <= high:
        middle = (low + high) // 2
        candidate = text[:middle]
        if predicate(candidate):
            best, low = candidate, middle + 1
        else:
            high = middle - 1
    return best


def fields(value, limit, counters):
    if isinstance(value, dict):
        return {key: fields(child, limit, counters) for key, child in value.items()}
    if isinstance(value, list):
        return [fields(child, limit, counters) for child in value]
    if fits(json_text(value), limit, counters):
        return value
    if isinstance(value, str):
        result = prefix(value, lambda item: fits(json_text(item), limit, counters))
        if result is not None:
            return result
    raise WorkFLowWeaveError("field_budget_insufficient", "字段预算无法容纳最小 JSON 标量")


def weight(value):
    if isinstance(value, dict):
        return 1 + sum(weight(child) for child in value.values())
    if isinstance(value, list):
        return 1 + sum(weight(child) for child in value)
    return 1 + len(value) if isinstance(value, str) else 1


def fragment(value, units):
    if isinstance(value, (dict, list)):
        remaining = units - 1
        result = {} if isinstance(value, dict) else []
        items = value.items() if isinstance(value, dict) else enumerate(value)
        for key, child in items:
            if remaining <= 0:
                break
            part = fragment(child, remaining)
            if isinstance(result, dict):
                result[key] = part
            else:
                result.append(part)
            remaining -= weight(child)
        return result
    if isinstance(value, str):
        return value[:max(0, units - 1)]
    return value


def render(parts, format):
    return "\n".join(
        part.original if part.original is not None and (not part.structured or format == "none")
        else serialize(part.value, format) if part.structured else str(part.value)
        for part in parts
    )


def envelope(source, body, format, truncated):
    return f"[source={source}; format={format}" + ("; incomplete" if truncated else "") + f"]\n{body}"


def shrink(parts, source, format, predicate, already_truncated):
    complete = envelope(source, render(parts, format), format, already_truncated)
    if predicate(complete):
        return complete, already_truncated
    # Re-serialization can save whitespace without discarding business values.
    compact = [Part(p.structured, p.value) for p in parts]
    complete = envelope(source, render(compact, format), format, already_truncated)
    if predicate(complete):
        return complete, already_truncated
    total = sum(weight(p.value) for p in parts)
    low, high, best = 1, total, None
    while low <= high:
        units = (low + high) // 2
        remaining, selected = units, []
        for part in compact:
            if remaining <= 0:
                break
            value = fragment(part.value, remaining)
            selected.append(Part(part.structured, value))
            remaining -= weight(part.value)
        try:
            candidate = envelope(source, render(selected, format), format, True)
            valid = predicate(candidate)
        except WorkFLowWeaveError as exc:
            if exc.code != "input_format_unsupported":
                raise
            valid = False
        if valid:
            best, low = candidate, units + 1
        else:
            high = units - 1
    if best is None:
        raise WorkFLowWeaveError("input_budget_insufficient", "预算不能容纳有效片段及来源/截取标识")
    return best, True


def process_input(snapshot, results, counters=()):
    config = snapshot.workflow.input_processing
    sources = snapshot.sources
    limited = config.total_tokens is not None or any(
        source.limits.item_tokens or source.limits.field_tokens for source in sources.values()
    )
    if limited and not counters:
        raise WorkFLowWeaveError("tokenizer_unavailable", "启用 token 限额需要消费模型的计量能力")
    prepared, views = {}, {}
    for result in results:
        source = sources[result.source_id]
        if result.status != "success":
            views[source.id] = InputView(source_id=source.id, status="skipped")
            continue
        try:
            raw = result.raw
            kind = source.call.kind
            parts = extract(raw, kind)
            filtered = [Part(p.structured, fields(p.value, source.limits.field_tokens, counters), p.original)
                        if p.structured else p for p in parts]
            changed = any(not equal_json(a.value, b.value) for a, b in zip(parts, filtered, strict=True))
            filtered = [Part(p.structured, p.value, None if changed and p.structured else p.original)
                        for p in filtered]
            text, truncated = shrink(filtered, source.id, config.format,
                                     lambda text, source=source: fits(text, source.limits.item_tokens, counters), changed)
            prepared[source.id] = (filtered, changed)
            views[source.id] = InputView(source_id=source.id, status="success", text=text, truncated=truncated)
        except WorkFLowWeaveError as exc:
            views[source.id] = InputView(source_id=source.id, status="failed", error=exc.info)
    ordered = [key for key in snapshot.workflow.sources if views[key].status == "success"]
    separator = snapshot.workflow.input_separator
    whole = separator.join(views[key].text for key in ordered)
    if fits(whole, config.total_tokens, counters):
        return whole, [views[key] for key in snapshot.workflow.sources]
    kept = []
    for index, key in enumerate(ordered):
        tail = ordered[index + 1:]
        note = "[omitted sources: " + ", ".join(tail) + "]" if tail else ""
        def combined(text, note=note):
            return separator.join([*kept, text, *([note] if note else [])])
        source = sources[key]
        try:
            parts, changed = prepared[key]
            text, truncated = shrink(parts, key, config.format,
                lambda text, source=source: fits(text, source.limits.item_tokens, counters)
                and fits(combined(text), config.total_tokens, counters), changed)
        except WorkFLowWeaveError as exc:
            if exc.code != "input_budget_insufficient":
                raise
            omitted = ordered[index:]
            note = "[omitted sources: " + ", ".join(omitted) + "]"
            candidate = separator.join([*kept, note])
            if not kept or not fits(candidate, config.total_tokens, counters):
                raise
            for ident in omitted:
                views[ident] = InputView(source_id=ident, status="success", truncated=True, omitted=True)
            return candidate, [views[ident] for ident in snapshot.workflow.sources]
        boundary = text != views[key].text
        views[key].text, views[key].truncated = text, truncated
        kept.append(text)
        if boundary:
            for ident in tail:
                views[ident] = InputView(source_id=ident, status="success", truncated=True, omitted=True)
            return separator.join([*kept, *([note] if note else [])]), [views[ident] for ident in snapshot.workflow.sources]
    return separator.join(kept), [views[key] for key in snapshot.workflow.sources]
