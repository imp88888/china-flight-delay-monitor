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


def parse_json_text(s):
    if not isinstance(s, str): return None
    try: return json.loads(s)
    except Exception: return None


def extract_records(result):
    found = []
    def walk(x):
        if isinstance(x, dict):
            if any(k in x for k in ("flightNo", "flight_no", "fnum", "flightNumber")):
                found.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str):
            parsed = parse_json_text(x)
            if parsed is not None: walk(parsed)
    walk(result)
    unique, seen = [], set()
    for item in found:
        key = json.dumps(item, ensure_ascii=False, sort_keys=True)
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def airline(f):
    m = re.search(r"\b(CZ|CA|MU)\s*\d{2,4}\b", text_of(f).upper())
    return m.group(1) if m else None


def delay_minutes(f):
    for key in ("delayMinutes", "delay_minutes", "delayMinute", "delayTime", "delay"):
        value = f.get(key)
        if isinstance(value, (int, float)): return int(value)
        if isinstance(value, str):
            m = re.search(r"(\d+)\s*(?:分钟|分|min|minutes?)", value, re.I)
            if m: return int(m.group(1))
    text = text_of(f)
    for pattern in (r"(?:延误|delay)[：:= ]*(\d+)\s*(?:分钟|分|min)?", r"(\d+)\s*(?:分钟|分|min)\s*(?:延误|delay)"):
        m = re.search(pattern, text, re.I)
        if m: return int(m.group(1))
    return 0


def main():
    if not API_KEY: raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    print("=== VariFlight MCP 自动工具发现 ===")
    print(f"MCP：{MCP_URL}")
    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = [x.get("name") for x in tools if isinstance(x, dict) and x.get("name")]
    print("工具发现：" + (", ".join(names) if names else "无"))
    required = {"searchFlightsByNumber", "searchFlightsByDepArr", "getTodayDate"}
    available = set(names)
    print("需要的工具：" + ", ".join(sorted(required & available)))
    missing = required - available
    if missing: print("⚠️ 缺少工具：" + ", ".join(sorted(missing)))

    today = datetime.now().strftime("%Y-%m-%d")
    if "getTodayDate" in available:
        try:
            result = tool("getTodayDate", {}, 2)
            m = re.search(r"20\d{2}-\d{2}-\d{2}", text_of(result))
            if m: today = m.group(0)
        except Exception as exc: print(f"⚠️ getTodayDate失败，使用系统日期：{exc}")
    print(f"日期：{today}")

    if "searchFlightsByDepArr" not in available:
        raise RuntimeError("MCP未提供searchFlightsByDepArr，无法查询国内航班")

    # 诊断阶段使用主要国内枢纽；不再伪装成全国全量扫描。
    routes = ["CAN-PEK", "CAN-PVG", "CAN-SHA", "CAN-SZX", "CAN-CTU", "CAN-HGH", "CAN-CKG", "CAN-KMG", "CAN-XMN", "CAN-WUH", "CAN-TSN", "CAN-TAO", "CAN-NKG", "CAN-XIY", "CAN-HAK"]
    total = 0; matched = {x: 0 for x in AIRLINES}; severe = []
    for i, route in enumerate(routes, 10):
        dep, arr = route.split("-", 1)
        try:
            result = tool("searchFlightsByDepArr", {"dep": dep, "arr": arr, "date": today}, i)
            recs = extract_records(result); total += len(recs)
            print(f"{route}: 解析航班 {len(recs)} 条")
            for flight in recs:
                code = airline(flight)
                if code not in AIRLINES: continue
                matched[code] += 1
                d = delay_minutes(flight)
                if d >= THRESHOLD_MINUTES: severe.append((code, flight, d, route))
        except Exception as exc: print(f"⚠️ {route}: {exc}")

    print("=== 结果 ===")
    print(f"解析航班：{total}")
    print(f"CZ：{matched['CZ']} | CA：{matched['CA']} | MU：{matched['MU']}")
    print(f"≥{THRESHOLD_MINUTES}分钟严重延误：{len(severe)}")
    for code, flight, d, route in severe:
        number = flight.get("flightNo") or flight.get("flight_no") or flight.get("fnum") or flight.get("flightNumber") or "UNKNOWN"
        print(f"🚨 {code}{number} | {route} | 延误 {d} 分钟")
        print(json.dumps(flight, ensure_ascii=False)[:800])
    if not severe: print("当前没有检测到达到阈值的CZ/CA/MU航班。")

if __name__ == "__main__": main()
