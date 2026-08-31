import json
import os
import re
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/tripmatch/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    r = requests.post(
        MCP_URL,
        headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-API-Key": API_KEY},
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

    print("=== VariFlight MCP 认证与参数诊断 ===")
    print(f"MCP：{MCP_URL}")
    print(f"API Key 已读取：YES | 长度：{len(API_KEY)}")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    targets = []
    for t in tools:
        if not isinstance(t, dict):
            continue
        name = t.get("name", "")
        if name in {"searchFlightsByDepArr", "searchFlightsByNumber"}:
            targets.append(t)
            print(f"\n工具：{name}")
            print(f"描述：{t.get('description', '')}")
            print("输入 schema：")
            print(json.dumps(t.get("inputSchema", {}), ensure_ascii=False, indent=2)[:5000])

    names = {t.get("name") for t in targets}
    today = beijing_now().strftime("%Y-%m-%d")
    print(f"\n北京时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"航班查询日期：{today}")

    if "searchFlightsByNumber" in names:
        print("\n=== 测试 searchFlightsByNumber（正确参数 fnum） ===")
        try:
            result = tool("searchFlightsByNumber", {"fnum": "MU2157", "date": today, "dep": "", "arr": ""}, 2)
            print(json.dumps(result, ensure_ascii=False)[:5000])
        except Exception as exc:
            print(f"航班号查询异常：{exc}")

    if "searchFlightsByDepArr" in names:
        print("\n=== 测试 searchFlightsByDepArr ===")
        try:
            result = tool("searchFlightsByDepArr", {"dep": "CAN", "arr": "PEK", "date": today}, 3)
            print(json.dumps(result, ensure_ascii=False)[:5000])
        except Exception as exc:
            print(f"机场查询异常：{exc}")

    print("\n=== 诊断结束 ===")


if __name__ == "__main__":
    main()
