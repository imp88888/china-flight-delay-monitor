import json
import os
import re
from datetime import datetime, timezone

import requests

MCP_URL = os.getenv(
    "VARIFLIGHT_MCP_URL",
    "https://ai.variflight.com/servers/aviation/mcp",
)
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))


def mcp_call(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": method,
        "params": params or {},
    }
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
        "X-API-Key": API_KEY,
    }
    response = requests.post(MCP_URL, headers=headers, json=payload, timeout=30)
    response.raise_for_status()

    text = response.text.strip()
    # Streamable HTTP may return JSON directly or SSE data lines.
    if text.startswith("data:"):
        chunks = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        text = chunks[-1] if chunks else text
    return json.loads(text)


def call_tool(name, arguments, request_id=2):
    result = mcp_call(
        "tools/call",
        {"name": name, "arguments": arguments},
        request_id=request_id,
    )
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def flatten_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(flatten_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(flatten_text(v) for v in value)
    return str(value)


def extract_delay_minutes(item):
    if not isinstance(item, dict):
        return 0

    for key in ("delay_minutes", "delayMinutes", "delay", "delayTime", "delay_time"):
        value = item.get(key)
        if isinstance(value, (int, float)):
            return int(value)
        if isinstance(value, str):
            match = re.search(r"(\d+)\s*(?:分钟|分|min|minutes?)", value, re.I)
            if match:
                return int(match.group(1))

    # Fall back to scheduled vs actual/estimated departure times.
    scheduled = next((item.get(k) for k in ("scheduledDeparture", "scheduled_departure", "depTime", "departureTime") if item.get(k)), None)
    actual = next((item.get(k) for k in ("estimatedDeparture", "estimated_departure", "actualDeparture", "actual_departure", "realDepTime") if item.get(k)), None)
    if scheduled and actual:
        try:
            s = datetime.fromisoformat(str(scheduled).replace("Z", "+00:00"))
            a = datetime.fromisoformat(str(actual).replace("Z", "+00:00"))
            if s.tzinfo is None:
                s = s.replace(tzinfo=timezone.utc)
            if a.tzinfo is None:
                a = a.replace(tzinfo=timezone.utc)
            return max(0, int((a - s).total_seconds() // 60))
        except (ValueError, TypeError):
            pass
    return 0


def extract_records(result):
    records = []
    structured = result.get("structuredContent") if isinstance(result, dict) else None
    content = result.get("content") if isinstance(result, dict) else None

    candidates = [structured, content, result]
    for candidate in candidates:
        if isinstance(candidate, list):
            records.extend(x for x in candidate if isinstance(x, dict))
        elif isinstance(candidate, dict):
            for key in ("flights", "data", "results", "items"):
                value = candidate.get(key)
                if isinstance(value, list):
                    records.extend(x for x in value if isinstance(x, dict))
    return records


def routes_from_env():
    raw = os.getenv("MONITOR_ROUTES", "CAN-PEK,CAN-SHA,CAN-PVG,CAN-SZX,CAN-CTU,CAN-HGH")
    routes = []
    for part in raw.split(","):
        if "-" not in part:
            continue
        dep, arr = [x.strip().upper() for x in part.split("-", 1)]
        if dep and arr and dep != arr:
            routes.append((dep, arr))
    return routes


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    today = datetime.now().strftime("%Y-%m-%d")
    severe = []
    for index, (dep, arr) in enumerate(routes_from_env(), start=10):
        result = call_tool(
            "searchFlightsByDepArr",
            {"dep": dep, "arr": arr, "date": today},
            request_id=index,
        )
        for flight in extract_records(result):
            delay = extract_delay_minutes(flight)
            if delay >= THRESHOLD_MINUTES:
                flight["_delay_minutes"] = delay
                severe.append(flight)

    print(f"中国国内严重延误航班（>={THRESHOLD_MINUTES}分钟）：{len(severe)}")
    for flight in severe:
        number = flight.get("flightNo") or flight.get("flight_no") or flight.get("fnum") or "UNKNOWN"
        print(f"{number}: {flight['_delay_minutes']} 分钟 | {flatten_text(flight)[:500]}")


if __name__ == "__main__":
    main()
