import json
import os
import re
from datetime import datetime

import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINES = {"CZ", "CA", "MU"}
# 先监控主要国内枢纽，避免每10分钟产生大量 MCP 额度消耗。
MONITOR_ROUTES = os.getenv("MONITOR_ROUTES", "CAN-PEK,CAN-PVG,CAN-SHA,CAN-SZX,CAN-CTU,CAN-HGH,CAN-CKG,CAN-KMG,CAN-XMN,CAN-WUH,CAN-TSN,CAN-TAO,CAN-NKG,CAN-XIY,CAN-HAK")


def mcp_call(method, params, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    response = requests.post(
        MCP_URL,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "X-API-Key": API_KEY,
        },
        json={"jsonrpc": "2.0", "id": request_id, "method": method, "params": params},
        timeout=30,
    )
    response.raise_for_status()
    text = response.text.strip()
    if text.startswith("data:"):
        lines = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")]
        text = lines[-1] if lines else text
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise RuntimeError(f"MCP returned non-JSON response: {text[:1000]}")


def call_tool(name, arguments, request_id):
    result = mcp_call("tools/call", {"name": name, "arguments": arguments}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def parse_json_string(text):
    text = text.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # MCP 有时会返回带说明文字的 JSON；尝试截取第一个 JSON 对象/数组。
        start_obj = text.find("{")
        start_arr = text.find("[")
        starts = [x for x in (start_obj, start_arr) if x >= 0]
        if not starts:
            return None
        start = min(starts)
        for end in range(len(text), start, -1):
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                continue
    return None


def records(result):
    out = []
    candidates = [result.get("structuredContent"), result.get("content"), result]
    for candidate in candidates:
        if isinstance(candidate, str):
            parsed = parse_json_string(candidate)
            if parsed is not None:
                out.extend(records(parsed if isinstance(parsed, dict) else {"data": parsed}))
            continue
        if isinstance(candidate, list):
            for item in candidate:
                if isinstance(item, dict):
                    if item.get("type") == "text" and isinstance(item.get("text"), str):
                        parsed = parse_json_string(item["text"])
                        if parsed is not None:
                            out.extend(records(parsed if isinstance(parsed, dict) else {"data": parsed}))
                        else:
                            out.append({"_text": item["text"]})
                    else:
                        out.append(item)
                elif isinstance(item, str):
                    parsed = parse_json_string(item)
                    if parsed is not None:
                        out.extend(records(parsed if isinstance(parsed, dict) else {"data": parsed}))
        elif isinstance(candidate, dict):
            # 直接的航班数组字段
            found_list = False
            for key in ("flights", "data", "results", "items", "list"):
                value = candidate.get(key)
                if isinstance(value, list):
                    found_list = True
                    out.extend(x if isinstance(x, dict) else {"_text": str(x)} for x in value)
                elif isinstance(value, str):
                    parsed = parse_json_string(value)
                    if isinstance(parsed, list):
                        found_list = True
                        out.extend(x if isinstance(x, dict) else {"_text": str(x)} for x in parsed)
            if not found_list and any(k in candidate for k in ("flightNo", "flight_no", "fnum", "airlineCode")):
                out.append(candidate)
    return out


def extract_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(extract_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(extract_text(v) for v in value)
    return str(value)


def airline_code(flight):
    text = extract_text(flight).upper()
    match = re.search(r"\b(CZ|CA|MU)\s*\d{2,4}\b", text)
    if match:
        return match.group(1)
    return None


def delay_minutes(flight):
    for key in ("delay_minutes", "delayMinutes", "delay", "delayTime", "delay_time", "delayMinute"):
        value = flight.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"(\d+)\s*(?:分钟|分|min|minutes?)", value, re.I)
            if match:
                return int(match.group(1))
    text = extract_text(flight)
    patterns = [
        r"(?:延误|delay)[：:= ]*(\d+)\s*(?:分钟|分|min)?",
        r"(\d+)\s*(?:分钟|分|min)\s*(?:延误|delay)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            return int(match.group(1))
    return 0


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    today = datetime.now().strftime("%Y-%m-%d")
    severe = []
    total = 0
    airline_counts = {x: 0 for x in sorted(AIRLINES)}
    routes = [x.strip().upper() for x in MONITOR_ROUTES.split(",") if "-" in x]

    print("=== 中国航班延误监控 ===")
    print(f"日期：{today}")
    print("航空公司：CZ / CA / MU")
    print(f"阈值：≥ {THRESHOLD_MINUTES} 分钟")
    print(f"监控航线：{len(routes)} 条")

    for index, route in enumerate(routes, start=10):
        dep, arr = route.split("-", 1)
        try:
            result = call_tool("searchFlightsByDepArr", {"dep": dep, "arr": arr, "date": today}, index)
            flights = records(result)
            total += len(flights)
            print(f"{route}: MCP返回 {len(flights)} 条")
            for flight in flights:
                code = airline_code(flight)
                if code not in AIRLINES:
                    continue
                airline_counts[code] += 1
                delay = delay_minutes(flight)
                if delay >= THRESHOLD_MINUTES:
                    severe.append((code, flight, delay, route))
        except Exception as exc:
            print(f"⚠️ {route} 查询失败：{exc}")

    print("--- 结果 ---")
    print(f"MCP 返回记录：{total}")
    print(f"识别 CZ/CA/MU：{sum(airline_counts.values())}")
    print(f"CZ：{airline_counts['CZ']} | CA：{airline_counts['CA']} | MU：{airline_counts['MU']}")
    print(f"严重延误航班：{len(severe)}")

    for code, flight, delay, route in severe:
        number = flight.get("flightNo") or flight.get("flight_no") or flight.get("fnum") or "UNKNOWN"
        print(f"🚨 {code} {number} | {route} | 延误 {delay} 分钟")
        print(json.dumps(flight, ensure_ascii=False)[:1000])


if __name__ == "__main__":
    main()
