from .declaration import ToolDeclaration, field, schema


async def invoke(arguments, context):
    return await context.gateway.invoke(arguments, context)


plugin = ToolDeclaration(
    "plugin", "Discover configured Collectors, read their call schema, or call one once.",
    schema({
        "action": field("string", "Operation", enum=["list", "schema", "call"]),
        "target": field("string", "Configured sources:id"),
        "arguments": field("object", "Call options/setters from target schema"),
        "query": field("string", "Filter capabilities by name or description"),
        "cursor": field("integer", "List offset", minimum=0),
    }, ["action"]), "read", invoke,
)
