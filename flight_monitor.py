import ast
import json
import os
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
DELAY_THRESHOLD = int(os.getenv("DELAY_THRESHOLD_MINUTES", "230"))
AIRLINE = "CZ"


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-API-Key": API_KEY,
    }
    response = requests.post(
        MCP_URL,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        timeout=30,
    )
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("data:"):
        data_lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = data_lines[-1] if data_lines else text
    return json.loads(text)


def tool(name, arguments=None, request_id=1):
    result = rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def beijing_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def extract_text(result):
    parts = []
    for item in result.get("content", []) if isinstance(result, dict) else []:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(item.get("text", ""))
    return "\n".join(parts)


def parse_flight_records(result):
    text = extract_text(result)
    marker = "Flight details:"
    if marker in text:
        text = text.split(marker, 1)[1].strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except Exception:
        try:
            obj = ast.literal_eval(text)
        except Exception:
            return []
    if isinstance(obj, dict):
        data = obj.get("data", [])
        return data if isinstance(data, list) else []
    return []


def is_domestic(flight):
    dep = str(flight.get("FlightDepcode", "")).upper()
    arr = str(flight.get("FlightArrcode", "")).upper()
    return bool(dep and arr)


def is_cz(flight):
    number = str(flight.get("FlightNo", "")).upper().replace(" ", "")
    return number.startswith(AIRLINE)


def delay_minutes(flight):
    plan = flight.get("FlightDeptimePlanDate")
    estimate = (
        flight.get("VeryZhunReadyDeptimeDate")
        or flight.get("FlightDeptimeReadyDate")
        or flight.get("FlightDeptimeDate")
    )
    if not plan or not estimate:
        return None
    try:
        planned = datetime.strptime(plan, "%Y-%m-%d %H:%M:%S")
        estimated = datetime.strptime(estimate, "%Y-%m-%d %H:%M:%S")
        return max(0, int((estimated - planned).total_seconds() // 60))
    except Exception:
        return None


def format_alert(flight, delay):
    return (
        f"{flight.get('FlightNo', '未知')}｜"
        f"{flight.get('FlightDep', flight.get('FlightDepcode', ''))}→"
        f"{flight.get('FlightArr', flight.get('FlightArrcode', ''))}｜"
        f"计划起飞：{flight.get('FlightDeptimePlanDate', '')}｜"
        f"预计延误：{delay} 分钟｜"
        f"状态：{flight.get('FlightState', '')}"
    )


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    now = beijing_now()
    date = now.strftime("%Y-%m-%d")
    print("=== CZ 全国国内航班延误监控 ===")
    print(f"北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("航空公司：CZ（中国南方航空）")
    print("起飞机场：不限")
    print("到达机场：不限")
    print("范围：中国国内")
    print(f"延误阈值：≥ {DELAY_THRESHOLD} 分钟（3小时50分钟）")
    print("检查周期：每30分钟")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    if "searchFlightsByDepArr" not in names:
        raise RuntimeError("Aviation MCP 缺少 searchFlightsByDepArr")

    # 全国模式：不限制出发/到达机场，只传日期。
    # MCP schema 将 dep/arr 定义为可选；如果服务端支持无约束查询，
    # 这一次调用即可返回当天航班清单，然后本程序筛选 CZ 国内航班。
    print("\n正在向 VariFlight 请求：当天、起降机场不限的航班清单……")
    try:
        result = tool(
            "searchFlightsByDepArr",
            {"date": date, "dep": None, "depcity": None, "arr": None, "arrcity": None},
            2,
        )
    except Exception as exc:
        print(f"全国航班清单查询失败：{exc}")
        print("当前 MCP 如果不支持‘起降机场均不限’，就不能仅靠该工具获得全国 CZ 全量清单；程序不会伪造结果或暴力遍历机场。")
        return

    records = parse_flight_records(result)
    print(f"MCP 返回航班记录：{len(records)} 条")

    cz_domestic = [f for f in records if is_cz(f) and is_domestic(f)]
    print(f"筛选 CZ 国内航班：{len(cz_domestic)} 条")

    alerts = []
    for flight in cz_domestic:
        delay = delay_minutes(flight)
        if delay is not None and delay >= DELAY_THRESHOLD:
            alerts.append((flight, delay))

    print(f"达到 ≥{DELAY_THRESHOLD} 分钟的严重延误：{len(alerts)} 条")
    if alerts:
        print("\n🚨 CZ 严重延误航班")
        for flight, delay in alerts:
            print(format_alert(flight, delay))
    else:
        print("\n本次没有发现达到 3小时50分钟 的 CZ 国内航班。")


if __name__ == "__main__":
    main()
