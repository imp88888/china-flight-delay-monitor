import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/aviation/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")


def key_fingerprint(key):
    if not key:
        return "NONE"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    visible = f"{key[:4]}...{key[-4:]}" if len(key) >= 8 else "****"
    return f"{visible} | SHA256={digest[:12]}"


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
    print(f"HTTP {r.status_code} | {method}")
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


def beijing_now():
    return datetime.now(timezone.utc).astimezone(timezone(timedelta(hours=8)))


def main():
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")

    print("=== VariFlight Aviation MCP 最小认证诊断 ===")
    print(f"MCP：{MCP_URL}")
    print(f"API Key 已读取：YES | 长度：{len(API_KEY)}")
    print(f"Key 安全指纹：{key_fingerprint(API_KEY)}")

    listing = rpc("tools/list", {}, 1)
    tools = listing.get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools if isinstance(t, dict) and t.get("name")}
    print(f"tools/list：成功 | 工具数量：{len(names)}")
    print("工具发现：" + ", ".join(sorted(names)))

    today = beijing_now().strftime("%Y-%m-%d")
    print(f"北京时间：{beijing_now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"航班查询日期：{today}")

    if "getTodayDate" in names:
        print("\n=== 测试 getTodayDate ===")
        try:
            result = tool("getTodayDate", {}, 2)
            print(json.dumps(result, ensure_ascii=False)[:2000])
        except Exception as exc:
            print(f"getTodayDate 异常：{exc}")

    if "searchFlightsByNumber" in names:
        print("\n=== 测试 searchFlightsByNumber ===")
        try:
            result = tool("searchFlightsByNumber", {"fnum": "MU2157", "date": today}, 3)
            print(json.dumps(result, ensure_ascii=False)[:6000])
        except Exception as exc:
            print(f"searchFlightsByNumber 异常：{exc}")

    print("\n=== 诊断结束 ===")


if __name__ == "__main__":
    main()
