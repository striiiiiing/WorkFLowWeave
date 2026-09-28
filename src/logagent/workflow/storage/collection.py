"""采集归档的规范化正文格式。"""


def collection_input(workflow, items):
    valid = [item["text"] for item in items if item["status"] == "success"]
    text = workflow.input_separator.join(valid)
    if workflow.include_counts and valid:
        text += "\n\n" + "\n".join(
            f"{item['source_id']}: {item['status']} ({item['count']})" for item in items
        )
    return text
