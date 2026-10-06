"""RESPONSE interceptor: adds MCP tool annotations to tools/list results, leaves everything else alone.

MODE is read from the environment so the demo can observe failure behaviour:
  normal  - annotate tools/list, pass everything else through
  raise   - raise an exception on every invocation
  garbage - return a payload that is not a valid interceptor output
"""
import os

# Keyed by the tool name WITHOUT the target prefix. The Gateway lists tools as <target>___<tool>.
ANNOTATIONS = {
    "read_file": {"title": "Read file", "readOnlyHint": True, "openWorldHint": False},
    "open_pr": {"title": "Open pull request", "readOnlyHint": False, "destructiveHint": False,
                "idempotentHint": False, "openWorldHint": True},
}


def _passthrough(resp):
    return {"interceptorOutputVersion": "1.0",
            "mcp": {"transformedGatewayResponse": {"statusCode": resp.get("statusCode", 200), "body": resp.get("body")}}}


def handler(event, context):
    mode = os.environ.get("MODE", "normal")
    if mode == "raise":
        raise RuntimeError("interceptor failure (demo)")
    if mode == "garbage":
        return {"not": "an interceptor output"}

    mcp = event["mcp"]
    resp = mcp["gatewayResponse"]
    method = (mcp["gatewayRequest"].get("body") or {}).get("method")
    body = resp.get("body")
    if method == "tools/list" and isinstance(body, dict):
        for tool in (body.get("result") or {}).get("tools", []):
            short = tool.get("name", "").split("___")[-1]
            if short in ANNOTATIONS:
                tool["annotations"] = ANNOTATIONS[short]
    return _passthrough({"statusCode": resp.get("statusCode", 200), "body": body})
