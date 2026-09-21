from .declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    return await context.workspace.write(**arguments, sandbox=context.config.sandbox.enabled)


plugin = ToolDeclaration(
    "write", "Overwrite, append, or replace one exact text match. Use read hash to prevent conflicts.",
    schema({
        "path": field("string", "Writable workspace path"),
        "mode": field("string", "Write mode", enum=["overwrite", "append", "replace"]),
        "content": field("string", "New content"),
        "old_text": field("string", "Replace mode: exact text occurring once", minLength=1),
        "expected_hash": field("string", "Hash from read; * requires the file to be absent"),
    }, ["path", "mode", "content"]), "exclusive", invoke,
)
