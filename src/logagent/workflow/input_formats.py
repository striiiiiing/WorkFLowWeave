"""Deterministic serializers with explicit, verified JSON value mappings."""
import csv
import html
import io
import json
import math

from logagent.errors import LogAgentError


def json_text(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def equal_json(left, right):
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(equal_json(left[k], right[k]) for k in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(equal_json(a, b) for a, b in zip(left, right, strict=True))
    return left == right


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    def number(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite JSON number")
        return result

    def constant(value):
        raise ValueError("nonstandard JSON constant")

    try:
        return True, json.loads(text, object_pairs_hook=pairs, parse_float=number,
                               parse_constant=constant)
    except (ValueError, RecursionError):
        return False, None


def _flat_table(value):
    if not isinstance(value, list) or not value or not isinstance(value[0], dict) or not value[0]:
        raise ValueError("requires a nonempty array of flat records")
    columns = list(value[0])
    if any(not isinstance(row, dict) or list(row) != columns
           or any(isinstance(v, (dict, list)) for v in row.values()) for row in value):
        raise ValueError("requires identical ordered fields and scalar cells")
    return columns


def serialize(value, format):
    try:
        if format == "none":
            return json_text(value)
        if format == "csv":
            columns = _flat_table(value)
            stream = io.StringIO(newline="")
            writer = csv.writer(stream, lineterminator="\n")
            writer.writerow(columns)
            writer.writerows([json_text(row[key]) for key in columns] for row in value)
            return stream.getvalue()
        if format == "md":
            rows = ["| JSON pointer | JSON value |", "| --- | --- |"]
            def visit(item, path):
                if isinstance(item, (dict, list)) and item:
                    iterator = item.items() if isinstance(item, dict) else enumerate(item)
                    # Container types preserve object/array identity, including numeric keys.
                    rows.append(f"| {escape(path)} | {escape(json_text({} if isinstance(item, dict) else []))} |")
                    for key, child in iterator:
                        visit(child, path + "/" + str(key).replace("~", "~0").replace("/", "~1"))
                else:
                    rows.append(f"| {escape(path)} | {escape(json_text(item))} |")
            def escape(text):
                return html.escape(text).replace("|", "&#124;").replace("\n", "&#10;").replace("\r", "&#13;")
            visit(value, "")
            return "\n".join(rows)
        if format == "ison":
            import ison_parser
            if isinstance(value, list):
                _flat_table(value)
            elif not isinstance(value, dict) or not value or any(isinstance(v, (dict, list)) for v in value.values()):
                raise ValueError("ISON supports a nonempty flat object or homogeneous flat records")
            text = ison_parser.dumps(ison_parser.from_dict({"data": value}, flatten=False))
            decoded = ison_parser.loads(text).to_dict().get("data")
        elif format == "toon":
            import toon_format
            text = toon_format.encode(value)
            decoded = toon_format.decode(text)
        elif format == "zon":
            import zon
            text = zon.encode(value)
            decoded = zon.decode(text)
        else:
            raise ValueError("unknown format")
        if not equal_json(value, decoded):
            raise ValueError("converter cannot preserve JSON types and values")
        return text
    except (ValueError, TypeError, OverflowError, KeyError, IndexError) as exc:
        raise LogAgentError("input_format_unsupported", f"{format}: {exc}") from exc
