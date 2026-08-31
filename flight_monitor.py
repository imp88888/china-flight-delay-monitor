import json
import os
import re
from datetime import datetime

import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINES = {"CZ", "CA", "MU"}
MONITOR_ROUTES = os.getenv("MONITOR_ROUTES", "CAN-PEK,CAN-PVG,CAN-SHA,CAN-SZX,CAN-CTU,CAN-HGH")


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
        data_lines = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")]
        text = data_lines[-1]
    return json.loads(text)


def call_tool(name, arguments, request_id):
    result = mcp_call("tools/call", {"name": name, "arguments": arguments}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def records(result):
    out = []
    for candidate in (result.get("structuredContent"), result.get("content"), result):
        if isinstance(candidate, list):
            out.extend(x for x in candidate if isinstance(x, dict))
        elif isinstance(candidate, dict):
            for key in ("flights", "data", "results", "items"):
                value = candidate.get(key)
                if isinstance(value, list):
                    out.extend(x for x in value if isinstance(x, dict))
    return out


def airline_code(flight):
    for key in ("airlineCode", "airline_code", "carrier", "airline"):
        value = flight.get(key)
        if value:
            match = re.search(r"\b(CZ|CA|MU)\b", str(value).upper())
            if match:
                return match.group(1)
    for key in ("flightNo", "flight_no", "fnum", "flightNumber"):
        value = str(flight.get(key, "")).upper()
        match = re.match(r"(CZ|CA|MU)\d+", value)
        if match:
            return match.group(1)
    return None


def delay_minutes(flight):
    for key in ("delay_minutes", "delayMinutes", "delay", "delayTime", "delay_time"):
        value = flight.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"(\d+)\s*(?:分钟|分|min|minutes?)", value, re.I)
            if match:
                return int(match.group(1))
    return 0


def main():
    today = datetime.now().strftime("%Y-%m-%d")
    severe = []
    routes = [x.strip().upper() for x in MONITOR_ROUTES.split(",") if "-" in x]

    for index, route in enumerate(routes, start=10):
        dep, arr = route.split("-", 1)
        result = call_tool(
            "searchFlightsByDepArr",
            {"dep": dep, "arr": arr, "date": today},
            index,
        )
        for flight in records(result):
            code = airline_code(flight)
            delay = delay_minutes(flight)
            if code in AIRLINES and delay >= THRESHOLD_MINUTES:
                severe.append((code, flight, delay))

    print("=== CZ / CA / MU 航班延误监控 ===")
    print(f"监控阈值：≥ {THRESHOLD_MINUTES} 分钟")
    print(f"严重延误航班：{len(severe)}")
    for code, flight, delay in severe:
        number = flight.get("flightNo") or flight.get("flight_no") or flight.get("fnum") or "UNKNOWN"
        print(f"🚨 {code} {number} | 延误 {delay} 分钟 | {json.dumps(flight, ensure_ascii=False)[:600]}")


if __name__ == "__main__":
    main()
