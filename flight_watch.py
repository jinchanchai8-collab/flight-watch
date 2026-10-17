#!/usr/bin/env python3
"""
台灣出發・直飛低價 / 錯價機票監控 → LINE 推播

資料來源
  1. Travelpayouts (Aviasales) Data API：各航線直飛最低價（direct=true）
  2. 錯價情報 RSS（Secret Flying、Fly4free 等），用關鍵字篩出台灣出發
判斷方式
  - 低於 config.json 各區域 max_price  → 低價
  - 低於各區域 error_price 或低於歷史中位數 × error_ratio → 疑似錯價 / Bug 票
  - 低於歷史中位數 × good_ratio → 比平常便宜
只用 Python 標準函式庫，不需 pip install。

用法
  python flight_watch.py              # 正式執行並推播
  python flight_watch.py --dry-run    # 只印出訊息，不推播、不寫歷史
  python flight_watch.py --test-line  # 傳一則測試訊息到 LINE
"""
import datetime as dt
import gzip
import html
import json
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
DATA_DIR = ROOT / "data"
HISTORY_FILE = DATA_DIR / "history.json"
SEEN_FILE = DATA_DIR / "seen.json"
TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).date()

CITY_NAMES = {
    "TYO": "東京", "OSA": "大阪", "NGO": "名古屋", "FUK": "福岡", "OKA": "沖繩",
    "SPK": "札幌", "SDJ": "仙台", "KMJ": "熊本", "HKD": "函館", "KOJ": "鹿兒島",
    "OKJ": "岡山", "TAK": "高松", "KIJ": "新潟", "HIJ": "廣島", "AOJ": "青森",
    "IBR": "茨城", "FSZ": "靜岡", "SEL": "首爾", "PUS": "釜山", "CJU": "濟州",
    "TAE": "大邱", "HKG": "香港", "MFM": "澳門", "BKK": "曼谷", "CNX": "清邁",
    "HKT": "普吉島", "SIN": "新加坡", "KUL": "吉隆坡", "PEN": "檳城", "BKI": "亞庇",
    "SGN": "胡志明市", "HAN": "河內", "DAD": "峴港", "CXR": "芽莊", "PQC": "富國島",
    "MNL": "馬尼拉", "CEB": "宿霧", "CRK": "克拉克", "JKT": "雅加達", "SUB": "泗水",
    "DPS": "峇里島", "PNH": "金邊", "RGN": "仰光", "LAX": "洛杉磯", "SFO": "舊金山",
    "SEA": "西雅圖", "NYC": "紐約", "ONT": "安大略", "DFW": "達拉斯", "IAH": "休士頓",
    "CHI": "芝加哥", "PHX": "鳳凰城", "YVR": "溫哥華", "YTO": "多倫多", "LON": "倫敦",
    "PAR": "巴黎", "AMS": "阿姆斯特丹", "VIE": "維也納", "MUC": "慕尼黑",
    "FRA": "法蘭克福", "PRG": "布拉格", "MIL": "米蘭", "ROM": "羅馬", "IST": "伊斯坦堡",
    "SYD": "雪梨", "BNE": "布里斯本", "MEL": "墨爾本", "AKL": "奧克蘭", "GUM": "關島",
    "TPE": "台北", "KHH": "高雄", "RMQ": "台中",
}


# ---------------------------------------------------------------- utilities
def http_get(url, headers=None, timeout=30):
    h = {"User-Agent": "Mozilla/5.0 (flight-watch bot)", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            data = gzip.decompress(data)
        return data


def http_post_json(url, payload, headers):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **headers},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def months_ahead(n):
    out, y, m = [], TODAY.year, TODAY.month
    for i in range(n):
        mm = m + i
        out.append(f"{y + (mm - 1) // 12:04d}-{(mm - 1) % 12 + 1:02d}")
    return out


def city_to_region():
    mapping = {}
    for region, r in CONFIG["regions"].items():
        for c in r["cities"]:
            mapping[c] = region
    return mapping


def name(code):
    return CITY_NAMES.get(code, code)


# ---------------------------------------------------- 1) Travelpayouts API
def fetch_direct_fares(token):
    """回傳所有台灣出發、直飛、目的地在監控清單內的票價。"""
    c2r = city_to_region()
    fares, errors = [], []
    for origin in CONFIG["origins"]:
        for month in months_ahead(CONFIG["months_ahead"]):
            params = {
                "origin": origin,
                "departure_at": month,
                "direct": "true",
                "sorting": "price",
                "currency": CONFIG["currency"],
                "one_way": "true" if CONFIG["one_way"] else "false",
                "limit": 1000,
                "page": 1,
            }
            if CONFIG.get("market"):
                params["market"] = CONFIG["market"]
            url = "https://api.travelpayouts.com/aviasales/v3/prices_for_dates?" + urllib.parse.urlencode(params)
            try:
                payload = json.loads(http_get(url, {"X-Access-Token": token}))
            except Exception as e:  # noqa: BLE001
                errors.append(f"Travelpayouts {origin} {month}: {e}")
                continue
            for t in payload.get("data") or []:
                dest = t.get("destination")
                if dest not in c2r:
                    continue
                if (t.get("transfers") or 0) != 0 or (t.get("return_transfers") or 0) != 0:
                    continue
                fares.append({
                    "origin": t.get("origin") or origin,
                    "origin_airport": t.get("origin_airport") or origin,
                    "dest": dest,
                    "dest_airport": t.get("destination_airport") or dest,
                    "region": c2r[dest],
                    "price": int(t["price"]),
                    "airline": t.get("airline", ""),
                    "flight": t.get("flight_number", ""),
                    "depart": (t.get("departure_at") or "")[:10],
                    "return": (t.get("return_at") or "")[:10],
                    "link": "https://www.aviasales.com" + t["link"] if t.get("link") else "",
                })
    return fares, errors


def cheapest_per_route(fares):
    best = {}
    for f in fares:
        key = f"{f['origin']}-{f['dest']}"
        if key not in best or f["price"] < best[key]["price"]:
            best[key] = f
    return best


def skyscanner_link(f):
    def ymd(d):
        return d[2:4] + d[5:7] + d[8:10]
    path = f"{f['origin_airport'].lower()}/{f['dest_airport'].lower()}/{ymd(f['depart'])}/"
    if f["return"]:
        path += f"{ymd(f['return'])}/"
    return f"https://www.skyscanner.com.tw/transport/flights/{path}?preferdirects=true"


def classify(fares, history):
    """依門檻與歷史價判斷，回傳 (deals, today_min)。"""
    rules = CONFIG["history_rules"]
    best = cheapest_per_route(fares)
    deals = []
    for key, f in best.items():
        reg = CONFIG["regions"][f["region"]]
        past = [p["price"] for p in history.get(key, []) if p["date"] != TODAY.isoformat()]
        median = statistics.median(past) if len(past) >= rules["min_history_points"] else None
        tag = None
        if f["price"] <= reg["error_price"] or (median and f["price"] <= median * rules["error_ratio"]):
            tag = "🚨疑似錯價"
        elif f["price"] <= reg["max_price"]:
            tag = "🔥低價"
        elif median and f["price"] <= median * rules["good_ratio"]:
            tag = "📉比平常便宜"
        if tag:
            deals.append({**f, "tag": tag, "median": int(median) if median else None})
    order = {"🚨疑似錯價": 0, "🔥低價": 1, "📉比平常便宜": 2}
    deals.sort(key=lambda d: (order[d["tag"]], d["price"] / CONFIG["regions"][d["region"]]["max_price"]))
    return deals, {k: v["price"] for k, v in best.items()}


def update_history(history, today_min, keep=90):
    for key, price in today_min.items():
        rows = [r for r in history.get(key, []) if r["date"] != TODAY.isoformat()]
        rows.append({"date": TODAY.isoformat(), "price": price})
        history[key] = rows[-keep:]
    return history


# ------------------------------------------------------ 2) 錯價情報 RSS
def fetch_feed_alerts():
    alerts, errors = [], []
    kw = [k.lower() for k in CONFIG["feed_keywords"]]
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)
    for url in CONFIG["error_fare_feeds"]:
        try:
            root = ET.fromstring(http_get(url))
        except Exception as e:  # noqa: BLE001
            errors.append(f"RSS {urllib.parse.urlparse(url).netloc}: {e}")
            continue
        for item in root.iter("item"):
            title = html.unescape(item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            desc = html.unescape(re.sub("<[^>]+>", " ", item.findtext("description") or ""))
            text = f"{title} {desc}".lower()
            if not any(k.lower() in text for k in kw):
                continue
            pub = item.findtext("pubDate")
            try:
                when = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S")
                when = when.replace(tzinfo=dt.timezone.utc)
                if when < cutoff:
                    continue
            except Exception:  # noqa: BLE001
                pass
            is_error = "error fare" in text or "mistake" in text
            alerts.append({"title": title, "link": link, "error": is_error})
    return alerts, errors


# ------------------------------------------------------------- 3) message
def build_message(deals, alerts, errors):
    lines = [f"✈️ 台灣出發直飛機票日報 {TODAY:%m/%d}"]
    if deals:
        lines.append("")
        trip = "單程" if CONFIG["one_way"] else "來回"
        for d in deals[: CONFIG["max_deals_in_message"]]:
            date = d["depart"][5:].replace("-", "/")
            if d["return"]:
                date += "–" + d["return"][5:].replace("-", "/")
            med = f"（平常約 {d['median']:,}）" if d["median"] else ""
            lines.append(f"{d['tag']} {name(d['origin'])}→{name(d['dest'])} {trip}")
            lines.append(f"NT${d['price']:,}{med}｜{d['airline']}{d['flight']} 直飛｜{date}")
            lines.append(skyscanner_link(d))
            lines.append("")
        if len(deals) > CONFIG["max_deals_in_message"]:
            lines.append(f"…另有 {len(deals) - CONFIG['max_deals_in_message']} 筆")
    if alerts:
        if lines[-1] != "":
            lines.append("")
        lines.append("📰 錯價 / 特價情報")
        for a in alerts[:6]:
            lines.append(("🚨 " if a["error"] else "• ") + a["title"])
            lines.append(a["link"])
    if not deals and not alerts:
        lines.append("今天沒有符合條件的低價直飛票。")
    if errors:
        lines.append("")
        lines.append(f"⚠️ {len(errors)} 個資料來源抓取失敗（詳見 GitHub Actions log）")
    lines.append("")
    lines.append("※ 價格來自快取，下單前請點連結確認")
    return "\n".join(lines).strip()


def chunk_text(text, size=4800, max_parts=5):
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > size:
            parts.append(cur)
            cur = ""
        cur += line + "\n"
    if cur.strip():
        parts.append(cur)
    return [p.strip() for p in parts][:max_parts]


def send_line(text):
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    if not token:
        raise SystemExit("缺少 LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")
    messages = [{"type": "text", "text": p} for p in chunk_text(text)]
    if user_id:
        url, body = "https://api.line.me/v2/bot/message/push", {"to": user_id, "messages": messages}
    else:
        url, body = "https://api.line.me/v2/bot/message/broadcast", {"messages": messages}
    status, resp = http_post_json(url, body, {"Authorization": f"Bearer {token}"})
    print(f"LINE {status} {resp}")


# ----------------------------------------------------------------- main
def main():
    args = set(sys.argv[1:])
    if "--test-line" in args:
        send_line("✅ 機票監控已連上 LINE，明天開始每天推播！")
        return

    dry = "--dry-run" in args
    token = os.environ.get("TRAVELPAYOUTS_TOKEN")
    errors = []
    fares = []
    if token:
        fares, errs = fetch_direct_fares(token)
        errors += errs
    else:
        errors.append("缺少 TRAVELPAYOUTS_TOKEN")

    history = load_json(HISTORY_FILE, {})
    deals, today_min = classify(fares, history)

    # 去重：同航線同日期同價格，N 天內不重複推播
    seen = load_json(SEEN_FILE, {})
    cutoff = (TODAY - dt.timedelta(days=CONFIG["dedupe_days"])).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    fresh = []
    for d in deals:
        k = f"{d['origin']}-{d['dest']}|{d['depart']}|{d['return']}|{d['price']}"
        if k not in seen:
            fresh.append(d)
            seen[k] = TODAY.isoformat()

    alerts, errs = fetch_feed_alerts()
    errors += errs
    for a in alerts:
        seen_key = "rss|" + a["link"]
        a["new"] = seen_key not in seen
        seen.setdefault(seen_key, TODAY.isoformat())
    alerts = [a for a in alerts if a["new"]]

    print(f"抓到 {len(fares)} 筆直飛票價、{len(today_min)} 條航線、{len(deals)} 筆符合條件（{len(fresh)} 筆新的）、{len(alerts)} 則情報")
    for e in errors:
        print("ERROR:", e)

    msg = build_message(fresh, alerts, errors)
    print("-" * 40)
    print(msg)
    print("-" * 40)

    if dry:
        return
    if fresh or alerts or CONFIG["send_when_nothing_found"]:
        send_line(msg)
    save_json(HISTORY_FILE, update_history(history, today_min))
    save_json(SEEN_FILE, seen)


if __name__ == "__main__":
    main()
