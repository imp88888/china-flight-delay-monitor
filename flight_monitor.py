import json
import os
import re
from datetime import datetime
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/tripmatch/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINES = {"CZ", "CA", "MU"}


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
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        print("MCP原始返回（前2000字符）：")
        print(text[:2000])
        raise


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


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    print("=== VariFlight MCP 完整诊断 ===")
    print(f"MCP：{MCP_URL}")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    print(f"工具数量：{len(tools)}")
    for t in tools:
        if isinstance(t, dict):
            print(f"- {t.get('name')} | {t.get('description', '')[:160]}")

    names = {t.get("name") for t in tools if isinstance(t, dict)}
    if "getTodayDate" in names:
        try:
            today_result = tool("getTodayDate", {}, 2)
            print("当天日期返回：", text_of(today_result)[:500])
        except Exception as e:
            print("getTodayDate错误：", e)

    if "searchFlightsByDepArr" not in names:
        raise RuntimeError("MCP 未提供 searchFlightsByDepArr")

    # 仅做低额度连通性测试，不宣称这是全国全量扫描。
    result = tool("searchFlightsByDepArr", {"dep": "CAN", "arr": "PEK", "date": datetime.now().strftime("%Y-%m-%d")}, 3)
    print("=== CAN→PEK MCP 原始结构 ===")
    print(json.dumps(result, ensure_ascii=False)[:5000])
    print("=== 诊断结束 ===")
    print("如果上面有航班数据，下一步再根据真实字段实现 CZ/CA/MU ≥120分钟筛选。")


if __name__ == "__main__":
    main()
