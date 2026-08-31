import os
import requests

THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
API_URL = os.getenv("VARIFLIGHT_MCP_API_URL", "")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")


def fetch_flights():
    if not API_URL:
        raise RuntimeError("VARIFLIGHT_MCP_API_URL is not configured")
    headers = {"Authorization": f"Bearer {API_KEY}"} if API_KEY else {}
    response = requests.get(API_URL, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json()


def is_domestic(flight):
    return flight.get("domestic", True) is True


def delay_minutes(flight):
    value = flight.get("delay_minutes", flight.get("delayMinutes", 0))
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def severe_delays(data):
    flights = data.get("data", data) if isinstance(data, dict) else data
    return [f for f in flights if is_domestic(f) and delay_minutes(f) >= THRESHOLD_MINUTES]


if __name__ == "__main__":
    data = fetch_flights()
    flights = severe_delays(data)
    print(f"严重延误航班（>={THRESHOLD_MINUTES}分钟）：{len(flights)}")
    for f in flights:
        print(f"{f.get('flight_no', f.get('flightNo', 'UNKNOWN'))}: {delay_minutes(f)} 分钟")
