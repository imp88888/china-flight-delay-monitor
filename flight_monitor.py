import ast
import json
import os
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
DELAY_THRESHOLD = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINE = os.getenv("MONITOR_AIRLINES", "CZ").strip().upper()
CACHE_FILE = os.getenv("CZ_FLIGHT_CACHE", "data/cz_flights_today.json")


def rpc(method, params=None, request_id=1):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-API-Key": API_KEY}
    response = requests.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, timeout=40)
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("data:"):
        lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = lines[-1] if lines else text
    return json.loads(text)


def beijing_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def raw_tool(name, arguments=None, request_id=1):
    result = rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def extract_text(result):
    return "\n".join(item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text")


def parse_records(result):
    text = extract_text(result)
    if "Flight details:" in text:
        text = text.split("Flight details:", 1)[1].strip()
    try:
        obj = json.loads(text)
    except Exception:
        try:
            obj = ast.literal_eval(text)
        except Exception:
            return []
    if isinstance(obj, dict) and isinstance(obj.get("data"), list):
        return obj["data"]
    return []


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    now = beijing_now()
    date = now.strftime("%Y-%m-%d")
    print("=== VariFlight MCP 单机场对诊断 ===")
    print(f"北京时间：{now:%Y-%m-%d %H:%M:%S}")
    print(f"测试日期：{date}")
    print("测试机场对：CAN → PEK")
    print("测试工具：searchFlightsByDepArr")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    target = next((t for t in tools if t.get("name") == "searchFlightsByDepArr"), None)
    if not target:
        raise RuntimeError("Aviation MCP 没有 searchFlightsByDepArr")
    print("工具已确认存在")
    print("工具定义：")
    print(json.dumps(target, ensure_ascii=False, indent=2))

    arguments = {"date": date, "dep": "CAN", "depcity": None, "arr": "PEK", "arrcity": None}
    print("\n实际发送参数：")
    print(json.dumps(arguments, ensure_ascii=False, indent=2))

    result = raw_tool("searchFlightsByDepArr", arguments, 1001)
    print("\n=== MCP 原始返回 ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))

    text = extract_text(result)
    print("\n=== MCP text ===")
    print(text)
    records = parse_records(result)
    print(f"\n解析得到航班记录：{len(records)} 条")
    for f in records[:20]:
        print(json.dumps(f, ensure_ascii=False))

    cz = [f for f in records if str(f.get("FlightNo", "")).upper().replace(" ", "").startswith(AIRLINE)]
    print(f"其中 CZ 航班：{len(cz)} 条")
    if not records:
        raise RuntimeError("CAN→PEK MCP 返回无法解析为航班记录；请根据上面的原始返回修正解析/参数")


if __name__ == "__main__":
    main()
