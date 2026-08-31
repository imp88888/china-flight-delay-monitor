import json
import os
import re
from datetime import datetime

import requests

MCP_URL = os.getenv("VARIFLIGHT_MCP_URL", "https://ai.variflight.com/servers/tripmatch/mcp")
API_KEY = os.getenv("VARIFLIGHT_API_KEY", "")
THRESHOLD_MINUTES = int(os.getenv("DELAY_THRESHOLD_MINUTES", "120"))
AIRLINES = {"CZ", "CA", "MU"}
ROUTES = os.getenv("MONITOR_ROUTES", "CAN-PEK,CAN-PVG,CAN-SHA,CAN-SZX,CAN-CTU,CAN-HGH")


def rpc(method, params=None, request_id=1):
    if not API_KEY:
        raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    r = requests.post(MCP_URL, headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","X-API-Key":API_KEY}, json={"jsonrpc":"2.0","id":request_id,"method":method,"params":params or {}}, timeout=30)
    r.raise_for_status()
    text = r.text.strip()
    if text.startswith("data:"):
        lines = [x[5:].strip() for x in text.splitlines() if x.startswith("data:")]
        text = lines[-1] if lines else text
    return json.loads(text)


def tool(name, arguments, request_id):
    result = rpc("tools/call", {"name":name,"arguments":arguments}, request_id)
    if "error" in result:
        raise RuntimeError(str(result["error"]))
    return result.get("result", {})


def parse_json_text(text):
    if not isinstance(text, str):
        return None
    try:
        return json.loads(text)
    except Exception:
        return None


def extract_records(result):
    found=[]
    def walk(x):
        if isinstance(x, dict):
            if any(k in x for k in ("flightNo","flight_no","fnum","airlineCode")):
                found.append(x)
            for v in x.values(): walk(v)
        elif isinstance(x, list):
            for v in x: walk(v)
        elif isinstance(x, str):
            parsed=parse_json_text(x)
            if parsed is not None: walk(parsed)
    walk(result)
    unique=[]; seen=set()
    for item in found:
        key=json.dumps(item,ensure_ascii=False,sort_keys=True)
        if key not in seen:
            seen.add(key); unique.append(item)
    return unique


def text_of(x):
    if isinstance(x,str): return x
    if isinstance(x,dict): return " ".join(text_of(v) for v in x.values())
    if isinstance(x,list): return " ".join(text_of(v) for v in x)
    return str(x)


def airline(f):
    m=re.search(r"\b(CZ|CA|MU)\s*\d{2,4}\b",text_of(f).upper())
    return m.group(1) if m else None


def delay(f):
    for k in ("delayMinutes","delay_minutes","delayMinute","delayTime","delay"):
        v=f.get(k)
        if isinstance(v,(int,float)): return int(v)
        if isinstance(v,str):
            m=re.search(r"(\d+)\s*(?:分钟|分|min|minutes?)",v,re.I)
            if m: return int(m.group(1))
    text=text_of(f)
    for p in (r"(?:延误|delay)[：:= ]*(\d+)\s*(?:分钟|分|min)?",r"(\d+)\s*(?:分钟|分|min)\s*(?:延误|delay)"):
        m=re.search(p,text,re.I)
        if m: return int(m.group(1))
    return 0


def main():
    if not API_KEY: raise RuntimeError("VARIFLIGHT_API_KEY is not configured")
    print("=== VariFlight MCP 诊断 ===")
    print(f"MCP：{MCP_URL}")
    listing=rpc("tools/list",request_id=1)
    names=[x.get("name") for x in listing.get("result",{}).get("tools",[])]
    print("工具发现：",", ".join(names) or "无")
    today_result=tool("getTodayDate",{},2)
    match=re.search(r"20\d{2}-\d{2}-\d{2}",text_of(today_result))
    today=match.group(0) if match else datetime.now().strftime("%Y-%m-%d")
    print(f"日期：{today}")
    total=0; matched={x:0 for x in AIRLINES}; severe=[]
    routes=[x.strip().upper() for x in ROUTES.split(",") if "-" in x]
    for i,route in enumerate(routes,10):
        dep,arr=route.split("-",1)
        try:
            result=tool("searchFlightsByDepArr",{"dep":dep,"arr":arr,"date":today},i)
            recs=extract_records(result); total+=len(recs)
            print(f"{route}: 解析航班 {len(recs)} 条")
            for f in recs:
                code=airline(f)
                if code not in AIRLINES: continue
                matched[code]+=1; d=delay(f)
                if d>=THRESHOLD_MINUTES: severe.append((code,f,d,route))
        except Exception as e:
            print(f"⚠️ {route}: {e}")
    print("=== 结果 ===")
    print(f"解析航班：{total}")
    print(f"CZ：{matched['CZ']} | CA：{matched['CA']} | MU：{matched['MU']}")
    print(f"≥{THRESHOLD_MINUTES}分钟严重延误：{len(severe)}")
    for code,f,d,route in severe:
        number=f.get("flightNo") or f.get("flight_no") or f.get("fnum") or "UNKNOWN"
        print(f"🚨 {code}{number} | {route} | 延误 {d} 分钟")
        print(json.dumps(f,ensure_ascii=False)[:800])
    if not severe:
        print("当前没有检测到达到阈值的 CZ/CA/MU 航班；请查看‘工具发现’和‘解析航班’数量。")

if __name__ == "__main__": main()
