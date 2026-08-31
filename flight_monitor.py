import ast
import json
import os
import time
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
DELAY_THRESHOLD = int(os.getenv("DELAY_THRESHOLD_MINUTES", "230"))
AIRLINE = "CZ"

# 全国国内机场发现种子。程序按出发机场查询当天航班，再筛选 CZ。
# 可通过环境变量 EXTRA_DEPARTURE_AIRPORTS 追加机场（逗号分隔）。
DEFAULT_DEPARTURE_AIRPORTS = "CAN,CSX,WUH,CGO,PEK,PKX,SHA,PVG,SZX,CTU,CKG,KMG,XIY,HAK,SYX,HGH,NKG,XMN,FOC,TAO,DLC,SHE,HRB,TSN,URC,NNG,KWL,ZYI,KWE,TYN,TAO,CGQ,KHN,HEF,HFE,WNZ,WNZ,NTG,JJN,LYG,YNT,WEH,WEF,JDZ,KHN,CGD,ZUH,MXZ,SWA,HAK,INC,XNN,LHW,XUZ,YIH,ENH,YNZ,LYI,TXN,HUZ,ACX,DDG,DNH,KHG,KRL,KRY,HTN,IQM"


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
        timeout=40,
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
    return "\n".join(
        item.get("text", "")
        for item in result.get("content", [])
        if isinstance(item, dict) and item.get("type") == "text"
    )


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


def is_cz(flight):
    return str(flight.get("FlightNo", "")).upper().replace(" ", "").startswith(AIRLINE)


def is_domestic(flight):
    dep = str(flight.get("FlightDepcode", "")).upper()
    arr = str(flight.get("FlightArrcode", "")).upper()
    # MCP 返回的是 IATA 三字码；这里先要求两端都有机场代码。
    return len(dep) == 3 and len(arr) == 3


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


def flight_key(flight):
    return (
        str(flight.get("FlightNo", "")).upper(),
        str(flight.get("FlightDeptimePlanDate", "")),
        str(flight.get("FlightDepcode", "")).upper(),
        str(flight.get("FlightArrcode", "")).upper(),
    )


def format_alert(flight, delay):
    return (
        f"{flight.get('FlightNo', '未知')}｜"
        f"{flight.get('FlightDep', flight.get('FlightDepcode', ''))}→"
        f"{flight.get('FlightArr', flight.get('FlightArrcode', ''))}｜"
        f"计划起飞：{flight.get('FlightDeptimePlanDate', '')}｜"
        f"预计延误：{delay} 分钟｜"
        f"状态：{flight.get('FlightState', '')}"
    )


def departure_airports():
    raw = os.getenv("DEPARTURE_AIRPORTS", DEFAULT_DEPARTURE_AIRPORTS)
    return list(dict.fromkeys(x.strip().upper() for x in raw.split(",") if x.strip()))


def discover_cz_flights(date):
    airports = departure_airports()
    found = {}
    print(f"全国航班发现：准备查询 {len(airports)} 个国内出发机场")
    for idx, dep in enumerate(airports, 1):
        print(f"[{idx}/{len(airports)}] 查询 {dep} → 不限到达机场")
        try:
            result = tool(
                "searchFlightsByDepArr",
                {"date": date, "dep": dep, "depcity": None, "arr": None, "arrcity": None},
                100 + idx,
            )
            records = parse_flight_records(result)
            for flight in records:
                if is_cz(flight) and is_domestic(flight):
                    found[flight_key(flight)] = flight
            print(f"    返回 {len(records)} 条，累计 CZ 国内航班 {len(found)} 条")
        except Exception as exc:
            print(f"    查询 {dep} 失败：{exc}")
        # 给 MCP/API 留出一点间隔，避免瞬时并发/限流。
        time.sleep(0.2)
    return list(found.values())


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    now = beijing_now()
    date = now.strftime("%Y-%m-%d")
    print("=== CZ 全国国内航班延误监控 ===")
    print(f"北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    print("航空公司：CZ（中国南方航空）")
    print("起飞机场：全国机场发现模式")
    print("到达机场：不限")
    print("范围：中国国内")
    print(f"延误阈值：≥ {DELAY_THRESHOLD} 分钟（3小时50分钟）")
    print("检查周期：每30分钟")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools if isinstance(t, dict)}
    if "searchFlightsByDepArr" not in names:
        raise RuntimeError("Aviation MCP 缺少 searchFlightsByDepArr")

    flights = discover_cz_flights(date)
    print(f"\n=== 全国 CZ 航班清单结果 ===")
    print(f"发现 CZ 国内航班：{len(flights)} 条")

    alerts = []
    for flight in flights:
        delay = delay_minutes(flight)
        if delay is not None and delay >= DELAY_THRESHOLD:
            alerts.append((flight, delay))

    print(f"达到 ≥{DELAY_THRESHOLD} 分钟的严重延误：{len(alerts)} 条")
    if alerts:
        print("\n🚨 CZ 严重延误航班")
        for flight, delay in sorted(alerts, key=lambda x: x[1], reverse=True):
            print(format_alert(flight, delay))
    else:
        print("\n本次没有发现达到 3小时50分钟 的 CZ 国内航班。")


if __name__ == "__main__":
    main()
