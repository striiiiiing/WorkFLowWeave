from .declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    return await context.sandbox.run(**arguments, config=context.config)


plugin = ToolDeclaration(
    "shell", "Run one shell command. Writes and sends cannot be undone by cancellation.",
    schema({
        "command": field("string", "Shell command", minLength=1),
        "cwd": field("string", "Working directory (workspace by default)"),
        "timeout": field("number", "Seconds before process-tree cancellation", exclusiveMinimum=0),
    }, ["command"]), "exclusive", invoke,
)
