from ..declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    return await context.workspace.read(
        **arguments, sandbox=context.config.sandbox.enabled,
        default_limit=context.config.read_lines,
        output_bytes=context.config.output_bytes,
    )


plugin = ToolDeclaration(
    "read", "Read UTF-8 text with a hash, or list a directory. Offset is zero-based.",
    schema({
        "path": field("string", "Workspace path"),
        "offset": field("integer", "Starting line or directory entry", minimum=0),
        "limit": field("integer", "Maximum lines or entries", minimum=1),
    }, ["path"]), "read", invoke,
)
