import json
import os
import hashlib
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
DELAY_THRESHOLD = int(os.getenv("DELAY_THRESHOLD_MINUTES", "230"))
AIRLINES = {"CZ", "MU"}


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-API-Key": API_KEY,
    }
    r = requests.post(
        MCP_URL,
        headers=headers,
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}},
        timeout=30,
    )
    r.raise_for_status()
    text = r.text.strip()
    if text.startswith("data:"):
        data = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")]
        text = data[-1] if data else text
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
    try:
        obj = eval(text, {"__builtins__": {}}, {})
        if isinstance(obj, dict):
            data = obj.get("data", [])
            return data if isinstance(data, list) else []
    except Exception:
        pass
    return []


def delay_minutes(flight):
    plan = flight.get("FlightDeptimePlanDate")
    estimate = flight.get("VeryZhunReadyDeptimeDate") or flight.get("FlightDeptimeReadyDate") or flight.get("FlightDeptimeDate")
    if not plan or not estimate:
        return None
    try:
        p = datetime.strptime(plan, "%Y-%m-%d %H:%M:%S")
        e = datetime.strptime(estimate, "%Y-%m-%d %H:%M:%S")
        return max(0, int((e - p).total_seconds() // 60))
    except Exception:
        return None


def domestic(f):
    dep = f.get("FlightDepcode", "")
    arr = f.get("FlightArrcode", "")
    return bool(dep and arr) and dep != arr


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    now = beijing_now()
    date = now.strftime("%Y-%m-%d")
    print("=== 中国航班延误监控 ===")
    print(f"北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"监控航空公司：{', '.join(sorted(AIRLINES))}")
    print(f"延误阈值：≥ {DELAY_THRESHOLD} 分钟（3小时50分钟）")

    listing = rpc("tools/list", {}, 1)
    names = {t.get("name") for t in listing.get("result", {}).get("tools", []) if isinstance(t, dict)}
    if "searchFlightsByNumber" not in names or "searchFlightsByDepArr" not in names:
        raise RuntimeError("Aviation MCP 缺少航班查询工具")

    # MCP 没有按航空公司批量查询的专用工具。优先读取环境变量提供的航班号列表；
    # 没有列表时用常见测试航班验证接口，并明确不伪造全网扫描结果。
    flight_numbers = [x.strip().upper() for x in os.getenv("MONITOR_FLIGHT_NUMBERS", "").split(",") if x.strip()]
    if not flight_numbers:
        print("未配置 MONITOR_FLIGHT_NUMBERS。为避免伪造‘全部航班’，本次只做接口可用性检查。")
        for fnum in ("CZ308", "MU2157"):
            result = tool("searchFlightsByNumber", {"fnum": fnum, "date": date}, 10)
            records = parse_flight_records(result)
            print(f"{fnum}：返回 {len(records)} 条")
        return

    alerts = []
    for fnum in flight_numbers:
        if fnum[:2] not in AIRLINES:
            continue
        try:
            result = tool("searchFlightsByNumber", {"fnum": fnum, "date": date}, 20)
            for f in parse_flight_records(result):
                if not domestic(f):
                    continue
                d = delay_minutes(f)
                if d is not None and d >= DELAY_THRESHOLD:
                    alerts.append((f, d))
        except Exception as exc:
            print(f"{fnum} 查询失败：{exc}")

    if alerts:
        print("\n🚨 发现严重延误航班")
        for f, d in alerts:
            print(f"{f.get('FlightNo','未知')}｜{f.get('FlightDep','')}→{f.get('FlightArr','')}｜延误 {d} 分钟｜状态：{f.get('FlightState','')}")
    else:
        print("\n本次没有发现达到 3小时50分钟 的 CZ/MU 国内航班。")


if __name__ == "__main__":
    main()
