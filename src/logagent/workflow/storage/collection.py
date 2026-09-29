"""采集归档的规范化正文格式。"""


def collection_input(workflow, items):
    valid = [item["text"] for item in items if item["status"] == "success"]
    return workflow.input_separator.join(valid)
