import json
import os
import re
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/tripmatch/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    r = requests.post(MCP_URL, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-API-Key": API_KEY}, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, timeout=30)
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


def text_of(x):
    if isinstance(x, str): return x
    if isinstance(x, dict): return " ".join(text_of(v) for v in x.values())
    if isinstance(x, list): return " ".join(text_of(v) for v in x)
    return str(x)


def get_beijing_today():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    print("=== VariFlight MCP 北京时间当天诊断 ===")
    print(f"MCP：{MCP_URL}")
    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools if isinstance(t, dict) and t.get("name")}
    print(f"工具数量：{len(names)}")
    print("工具发现：" + ", ".join(sorted(names)))

    # 航班查询日期以中国标准时间（UTC+8）为准，不使用 MCP 的错误日期。
    today = get_beijing_today()
    print(f"北京时间：{datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"航班查询日期：{today}")

    if "searchFlightsByDepArr" not in names:
        raise RuntimeError("MCP 未提供 searchFlightsByDepArr")

    # 低额度诊断：验证当天日期进入真实航班查询请求。
    result = tool("searchFlightsByDepArr", {"dep": "CAN", "arr": "PEK", "date": today}, 2)
    print("=== CAN→PEK 当天查询原始返回 ===")
    print(json.dumps(result, ensure_ascii=False)[:5000])
    print("=== 诊断结束 ===")


if __name__ == "__main__":
    main()
