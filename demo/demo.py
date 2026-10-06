#!/usr/bin/env python3
"""Shows what a Gateway Lambda target can and cannot say about tool annotations, and what a RESPONSE interceptor adds.

A1-A4 are asserted (PASS/FAIL). A5 is observational: it records what a client receives when the interceptor fails,
because the right behaviour there is a judgement call, not something this demo can assert for you.
"""
import json, os, sys, time, urllib.request, urllib.error
import boto3
from botocore.exceptions import ParamValidationError

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = json.load(open(os.path.join(ROOT, "cdk", "cdk.outputs.json")))["GatewayToolAnnotations"]
REGION = OUT["Region"]
PW = "Demo-Passw0rd!"  # throwaway user in a throwaway pool, destroyed with the stack
cog = boto3.client("cognito-idp", region_name=REGION)
lam = boto3.client("lambda", region_name=REGION)
ctl = boto3.client("bedrock-agentcore-control", region_name=REGION)
results = []


def token():
    try:
        cog.admin_create_user(UserPoolId=OUT["UserPoolId"], Username="dev", MessageAction="SUPPRESS")
    except cog.exceptions.UsernameExistsException:
        pass
    cog.admin_set_user_password(UserPoolId=OUT["UserPoolId"], Username="dev", Password=PW, Permanent=True)
    r = cog.admin_initiate_auth(UserPoolId=OUT["UserPoolId"], ClientId=OUT["ClientId"], AuthFlow="ADMIN_USER_PASSWORD_AUTH",
                                AuthParameters={"USERNAME": "dev", "PASSWORD": PW})
    return r["AuthenticationResult"]["AccessToken"]


def rpc(url, tok, method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json",
                                          "Accept": "application/json, text/event-stream"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            try: return r.status, json.loads(raw)
            except Exception: return r.status, {"raw": raw[:300]}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try: return e.code, json.loads(raw)
        except Exception: return e.code, {"raw": raw[:300]}


def check(label, ok, detail=""):
    results.append(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"\n       {detail}" if detail else ""))


def tools_of(body):
    return {t["name"]: t for t in (body.get("result") or {}).get("tools", [])}


def set_mode(mode):
    fn = OUT["InterceptorFunction"]
    lam.update_function_configuration(FunctionName=fn, Environment={"Variables": {"MODE": mode}})
    lam.get_waiter("function_updated_v2").wait(FunctionName=fn)
    time.sleep(2)


def short(x, n=170):
    s = json.dumps(x); return s if len(s) <= n else s[:n] + "..."


def main():
    tok = token()
    PLAIN, ANNO = OUT["PlainGatewayUrl"], OUT["AnnotatedGatewayUrl"]

    print("\n== A1. Can a Lambda target's tool definition carry annotations? ==")
    try:
        ctl.create_gateway_target(
            gatewayIdentifier="gw-demo-not-created", name="x",
            targetConfiguration={"mcp": {"lambda": {"lambdaArn": "arn:aws:lambda:us-east-1:000000000000:function:x", "toolSchema": {
                "inlinePayload": [{"name": "t", "description": "d", "inputSchema": {"type": "object"},
                                   "annotations": {"readOnlyHint": True}}]}}}})
        check("A1 the API accepted an annotations field", False, "unexpected: it did not reject it")
    except ParamValidationError as e:
        check("A1 the SDK's API model has no annotations field on a tool definition", True, str(e).strip().splitlines()[-1][:160])

    print("\n== A2. Plain gateway: tools/list ==")
    s, b = rpc(PLAIN, tok, "tools/list"); plain = tools_of(b)
    for n, t in plain.items(): print(f"       {n}: annotations = {t.get('annotations', '(none)')}")
    check("A2 plain gateway lists both tools with no annotations", len(plain) == 2 and all("annotations" not in t for t in plain.values()))

    print("\n== A3. Intercepted gateway: tools/list ==")
    s, b = rpc(ANNO, tok, "tools/list"); anno = tools_of(b)
    os.makedirs(os.path.join(ROOT, "docs"), exist_ok=True)
    json.dump(b, open(os.path.join(ROOT, "docs", "tools-list-intercepted.json"), "w"), indent=2)
    for n, t in anno.items(): print(f"       {n}: annotations = {t.get('annotations', '(none)')}")
    ra = anno.get("github___read_file", {}).get("annotations", {}); oa = anno.get("github___open_pr", {}).get("annotations", {})
    check("A3 read_file is readOnlyHint=true and open_pr is readOnlyHint=false, as the client sees them",
          ra.get("readOnlyHint") is True and oa.get("readOnlyHint") is False)

    print("\n== A4. tools/call through the intercepted gateway ==")
    s, b = rpc(ANNO, tok, "tools/call", {"name": "github___read_file", "arguments": {"path": "README.md"}})
    check("A4 read_file call works through the interceptor", "error" not in b and not (b.get("result") or {}).get("isError"), short(b))
    s, b = rpc(ANNO, tok, "tools/call", {"name": "github___open_pr", "arguments": {"title": "demo"}})
    check("A4 open_pr call works through the interceptor", "error" not in b and not (b.get("result") or {}).get("isError"), short(b))

    print("\n== A5. Failure mode (observed, not asserted): what does the client get when the interceptor fails? ==")
    for mode in ("raise", "garbage"):
        set_mode(mode)
        print(f"   interceptor MODE={mode}")
        for label, method, params in (("tools/list", "tools/list", None),
                                      ("tools/call read_file", "tools/call", {"name": "github___read_file", "arguments": {"path": "README.md"}})):
            s, b = rpc(ANNO, tok, method, params)
            print(f"     intercepted gateway, {label}: HTTP {s} {short(b, 150)}")
        s, b = rpc(PLAIN, tok, "tools/call", {"name": "github___read_file", "arguments": {"path": "README.md"}})
        print(f"     plain gateway (control), tools/call read_file: HTTP {s} {short(b, 110)}")
    set_mode("normal")
    s, b = rpc(ANNO, tok, "tools/list")
    check("A5 restoring MODE=normal restores annotations", bool(tools_of(b).get("github___read_file", {}).get("annotations")))

    print(f"\n{sum(results)}/{len(results)} asserted checks passed")
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
