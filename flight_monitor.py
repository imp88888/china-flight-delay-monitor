import json
import os
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    # Aviation MCP historically supports the api_key query parameter; keep the
    # documented header forms too so the hosted endpoint can authenticate either way.
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-API-Key": API_KEY,
        "X-VARIFLIGHT-KEY": API_KEY,
    }
    query = {"api_key": API_KEY} if "/servers/aviation/mcp" in MCP_URL else None

    r = requests.post(
        MCP_URL,
        params=query,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        timeout=30,
    )
    print(f"HTTP {r.status_code} | {method}")
    r.raise_for_status()
    text = r.text.strip()
    if text.startswith("data:"):
        lines = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")]
        text = lines[-1] if lines else text
    return json.loads(text)


def tool(name, arguments=None, request_id=1):
    result = rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def beijing_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    print("=== VariFlight Aviation MCP 认证诊断 ===")
    print(f"MCP：{MCP_URL}")
    print(f"API Key 已读取：YES | 长度：{len(API_KEY)}")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools if isinstance(t, dict) and t.get("name")}
    print(f"工具数量：{len(names)}")
    print("工具发现：" + ", ".join(sorted(names)))

    today = beijing_now().strftime("%Y-%m-%d")
    print(f"北京时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"航班查询日期：{today}")

    for name in ("searchFlightsByNumber", "searchFlightsByDepArr"):
        if name not in names:
            print(f"跳过：Aviation MCP 未提供 {name}")
            continue
        print(f"\n=== 测试 {name} ===")
        try:
            if name == "searchFlightsByNumber":
                args = {"fnum": "MU2157", "date": today}
            else:
                args = {"dep": "CAN", "arr": "PEK", "date": today}
            result = tool(name, args, 2 if name.endswith("Number") else 3)
            print(json.dumps(result, ensure_ascii=False)[:6000])
        except Exception as exc:
            print(f"查询异常：{exc}")

    print("\n=== Aviation MCP 诊断结束 ===")


if __name__ == "__main__":
    main()
