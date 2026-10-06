"""Mock target with two tools. Reads canned text, 'opens' a PR as a string. Touches nothing."""


def handler(event, context):
    # The Gateway names the tool in the client context as <target>___<tool>. Fall back to the argument shape.
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    name = (custom.get("bedrockAgentCoreToolName") or "").split("___")[-1]
    if not name:
        name = "read_file" if "path" in event else "open_pr"
    if name == "read_file":
        return {"path": event.get("path"), "content": "canned file content (mock)"}
    return {"pr": f"https://example.invalid/pull/1", "title": event.get("title")}
