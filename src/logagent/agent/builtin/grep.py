from .declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    return await context.workspace.grep(
        **arguments, sandbox=context.config.sandbox.enabled,
        default_limit=context.config.grep_matches,
        output_bytes=context.config.output_bytes,
    )


plugin = ToolDeclaration(
    "grep", "Search text with ripgrep; returns paths, line numbers and excerpts.",
    schema({
        "pattern": field("string", "Regular expression"),
        "path": field("string", "File or directory (workspace by default)"),
        "glob": field("string", "Filename glob"),
        "limit": field("integer", "Maximum hits", minimum=1),
    }, ["pattern"]), "read", invoke,
)
