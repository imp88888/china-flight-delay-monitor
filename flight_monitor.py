import ast
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
DELAY_THRESHOLD = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINE = os.getenv("MONITOR_AIRLINES", "CZ").strip().upper()
CACHE_FILE = os.getenv("CZ_FLIGHT_CACHE", "data/cz_flights_today.json")

DISCOVERY_HUBS = ["CAN", "SZX", "PEK", "PKX", "PVG", "SHA", "WUH", "CSX", "CTU", "CKG", "KMG", "XIY"]
DEPARTURE_AIRPORTS = [x.strip().upper() for x in os.getenv(
    "DEPARTURE_AIRPORTS",
    "CAN,CSX,WUH,CGO,PEK,PKX,SHA,PVG,SZX,CTU,CKG,KMG,XIY,HAK,SYX,HGH,NKG,XMN,FOC,TAO,DLC,SHE,HRB,TSN,URC,NNG,KWL,KWE,TYN,CGQ,KHN,HFE,WNZ,NTG,JJN,LYG,YNT,WEH,WEF,JDZ,ZUH,SWA,INC,LHW,XUZ,YIH,ENH,YNZ,LYI,TXN,HUZ,ACX,DDG,DNH,KHG,KRL,KRY,HTN,IQM"
).split(",") if x.strip()]


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", "X-API-Key": API_KEY}
    response = requests.post(MCP_URL, headers=headers, json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}, timeout=40)
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("data:"):
        lines = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = lines[-1] if lines else text
    return json.loads(text)


def tool(name, arguments=None, request_id=1):
    result = rpc("tools/call", {"name": name, "arguments": arguments or {}}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def beijing_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def extract_text(result):
    return "\n".join(item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text")


def parse_flight_records(result):
    text = extract_text(result)
    if "Flight details:" in text:
        text = text.split("Flight details:", 1)[1].strip()
    if not text:
        return []
    try:
        obj = json.loads(text)
    except Exception:
        try:
            obj = ast.literal_eval(text)
        except Exception:
            return []
    data = obj.get("data", []) if isinstance(obj, dict) else []
    return data if isinstance(data, list) else []


def is_cz(flight):
    return str(flight.get("FlightNo", "")).upper().replace(" ", "").startswith(AIRLINE)


def is_domestic(flight):
    dep = str(flight.get("FlightDepcode", "")).upper()
    arr = str(flight.get("FlightArrcode", "")).upper()
    return len(dep) == 3 and len(arr) == 3


def flight_key(f):
    return (str(f.get("FlightNo", "")), str(f.get("FlightDeptimePlanDate", "")), str(f.get("FlightDepcode", "")), str(f.get("FlightArrcode", "")))


def load_cache(date):
    if not os.path.exists(CACHE_FILE):
        return []
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
        if payload.get("date") != date:
            return []
        flights = payload.get("flights", [])
        return flights if isinstance(flights, list) else []
    except Exception:
        return []


def save_cache(date, flights):
    directory = os.path.dirname(CACHE_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"date": date, "updated_at": beijing_now().isoformat(), "flights": flights}, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, CACHE_FILE)


def discover_pair(date, dep, arr, request_id):
    result = tool("searchFlightsByDepArr", {
        "date": date,
        "dep": dep,
        "depcity": None,
        "arr": arr,
        "arrcity": None,
    }, request_id)
    return dep, arr, parse_flight_records(result)


def discover_cz_flights(date):
    found = {}
    pairs = [(dep, arr) for dep in DEPARTURE_AIRPORTS for arr in DISCOVERY_HUBS if dep != arr]
    workers = min(8, max(1, len(pairs)))
    print(f"全国 CZ 航班发现：有效机场对 {len(pairs)} 对，并发 {workers}")
    print("采用并发发现，避免第一次扫描超过 GitHub Actions 超时。")

    completed = 0
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(discover_pair, date, dep, arr, 1000 + idx): (dep, arr)
            for idx, (dep, arr) in enumerate(pairs, 1)
        }
        for future in as_completed(futures):
            dep, arr = futures[future]
            completed += 1
            try:
                _, _, records = future.result()
                for f in records:
                    if is_cz(f) and is_domestic(f):
                        found[flight_key(f)] = f
                print(f"[{completed}/{len(pairs)}] {dep} → {arr}：返回 {len(records)} 条，累计 CZ 国内航班 {len(found)} 条")
            except Exception as exc:
                print(f"[{completed}/{len(pairs)}] {dep} → {arr}：查询失败：{exc}")

    flights = list(found.values())
    save_cache(date, flights)
    print(f"全国 CZ 航班发现完成：{len(flights)} 条")
    print(f"缓存已写入：{CACHE_FILE}")
    return flights


def query_cached_status(date, cached):
    updated = []
    for idx, old in enumerate(cached, 1):
        fnum = str(old.get("FlightNo", "")).strip()
        if not fnum.startswith(AIRLINE):
            continue
        print(f"[{idx}/{len(cached)}] 更新 {fnum} {old.get('FlightDepcode','')}→{old.get('FlightArrcode','')}")
        try:
            result = tool("searchFlightsByNumber", {"fnum": fnum, "date": date, "dep": old.get("FlightDepcode") or None, "arr": old.get("FlightArrcode") or None}, 5000 + idx)
            records = parse_flight_records(result)
            if records:
                match = next((x for x in records if flight_key(x) == flight_key(old)), None)
                updated.append(match or records[0])
            else:
                updated.append(old)
        except Exception as exc:
            print(f"    状态更新失败，保留缓存：{exc}")
            updated.append(old)
    save_cache(date, updated)
    return updated


def delay_minutes(flight, now):
    plan = flight.get("FlightDeptimePlanDate")
    estimate = flight.get("VeryZhunReadyDeptimeDate") or flight.get("FlightDeptimeReadyDate") or flight.get("FlightDeptimeDate")
    if estimate and plan:
        try:
            p = datetime.strptime(plan, "%Y-%m-%d %H:%M:%S")
            a = datetime.strptime(estimate, "%Y-%m-%d %H:%M:%S")
            return max(0, int((a - p).total_seconds() // 60))
        except Exception:
            pass
    if plan:
        try:
            p = datetime.strptime(plan, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone(timedelta(hours=8)))
            if p.date() == now.date() and now > p:
                return max(0, int((now - p).total_seconds() // 60))
        except Exception:
            pass
    return None


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    now = beijing_now()
    date = now.strftime("%Y-%m-%d")
    print("=== CZ 全国国内航班延误监控 ===")
    print(f"北京时间：{now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"航空公司：{AIRLINE}（中国南方航空）")
    print("起飞机场：全国机场")
    print("到达机场：不限（通过有效机场对发现）")
    print("范围：中国国内")
    print(f"延误阈值：≥ {DELAY_THRESHOLD} 分钟")
    print("检查周期：每30分钟")

    listing = rpc("tools/list", {}, 1)
    names = {t.get("name") for t in listing.get("result", {}).get("tools", []) if isinstance(t, dict)}
    required = {"searchFlightsByDepArr", "searchFlightsByNumber"}
    missing = required - names
    if missing:
        raise RuntimeError(f"Aviation MCP 缺少工具：{', '.join(sorted(missing))}")

    cached = load_cache(date)
    if cached:
        print(f"发现当天 CZ 缓存：{len(cached)} 条")
        print("本轮不再扫描全国机场，只更新已发现航班。")
        flights = query_cached_status(date, cached)
    else:
        print("没有当天缓存：执行一次全国 CZ 航班发现。")
        flights = discover_cz_flights(date)

    print("\n=== CZ 全国国内航班监控结果 ===")
    print(f"当前缓存 CZ 国内航班：{len(flights)} 条")
    alerts = []
    for f in flights:
        d = delay_minutes(f, now)
        if d is not None and d >= DELAY_THRESHOLD:
            alerts.append((f, d))
    print(f"达到 ≥{DELAY_THRESHOLD} 分钟的严重延误：{len(alerts)} 条")
    if alerts:
        print("\n🚨 CZ 严重延误航班")
        for f, d in sorted(alerts, key=lambda x: x[1], reverse=True):
            print(f"{f.get('FlightNo','未知')}｜{f.get('FlightDep',f.get('FlightDepcode',''))}→{f.get('FlightArr',f.get('FlightArrcode',''))}｜计划起飞：{f.get('FlightDeptimePlanDate','')}｜延误：{d} 分钟｜状态：{f.get('FlightState','')}")
    else:
        print(f"本次没有发现达到 {DELAY_THRESHOLD} 分钟的 CZ 国内航班。")


if __name__ == "__main__":
    main()
