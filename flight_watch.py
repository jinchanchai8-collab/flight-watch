#!/usr/bin/env python3
"""
台灣出發・直飛低價 / 錯價機票監控 → LINE 推播（v3）

核心邏輯
  1. 每條航線只跟「自己、同一個出發月份」的價格比，算出便宜幾 %
     → 歐美長程線不會因絕對價格高被埋沒，淡季整月便宜也不會被誤判
  2. 篩選：至少 7 天後出發；旅行天數依地區（亞洲 5–15 天、長程 10 天以上…）
  3. 排名：依降價 % 排序，取前 10 名，並分散國家（每國最多 2 筆、
     每區最多 4 筆、保留 2 個長程線名額）
  4. 疑似錯價：降幅超過該航線的錯價門檻（會自我學習調整）
  5. 自我檢討：疑似錯價 1～2 天內消失＝真錯價（門檻調低）；
     3 天後還在＝淡季/常態促銷（門檻調高）
  6. 標示：樣本少、廉航（附加行李概估價）、台灣連假（需請幾天假）、當地節日

執行模式
  python flight_watch.py              # 每日日報（早上 8 點）
  python flight_watch.py --alert-only # 錯價快報：只在發現新的 🚨 時推播
  python flight_watch.py --dry-run    # 只印出，不推播、不寫資料
  python flight_watch.py --test-line  # LINE 連線測試
  （GitHub 排程會自動依時段判斷模式）
"""
import datetime as dt
import gzip
import html
import json
import os
import re
import statistics
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
HOLIDAYS = json.loads((ROOT / "holidays.json").read_text(encoding="utf-8")) if (ROOT / "holidays.json").exists() else {"taiwan": [], "foreign": []}
DATA_DIR = ROOT / "data"
BASELINE_FILE = DATA_DIR / "baseline.json"
LEARN_FILE = DATA_DIR / "learning.json"
SEEN_FILE = DATA_DIR / "seen.json"
STATE_FILE = DATA_DIR / "state.json"          # 記錄今天日報是否已送出（備援排程用）
TZ = dt.timezone(dt.timedelta(hours=8))
TODAY = dt.datetime.now(TZ).date()
TODAY_S = TODAY.isoformat()

R = CONFIG["ranking"]
LEARN = CONFIG["learning"]
DIV = CONFIG["diversity"]
LCC = CONFIG["lcc"]
HF = CONFIG.get("holiday_focus", {})
BIZ = CONFIG.get("business", {"enabled": False})
PARTY = CONFIG.get("party", {}).get("show_for", 0)
LAST_RUN_FILE = DATA_DIR / "last_run.json"     # 每次執行的統計（除錯用，不含金鑰）

CITY = {  # 代碼: (中文名, 國家)
    "TYO": ("東京", "日本"), "OSA": ("大阪", "日本"), "NGO": ("名古屋", "日本"), "FUK": ("福岡", "日本"),
    "OKA": ("沖繩", "日本"), "SPK": ("札幌", "日本"), "SDJ": ("仙台", "日本"), "KMJ": ("熊本", "日本"),
    "HKD": ("函館", "日本"), "KOJ": ("鹿兒島", "日本"), "OKJ": ("岡山", "日本"), "TAK": ("高松", "日本"),
    "KIJ": ("新潟", "日本"), "HIJ": ("廣島", "日本"), "AOJ": ("青森", "日本"), "IBR": ("茨城", "日本"),
    "FSZ": ("靜岡", "日本"), "SEL": ("首爾", "韓國"), "PUS": ("釜山", "韓國"), "CJU": ("濟州", "韓國"),
    "TAE": ("大邱", "韓國"), "HKG": ("香港", "香港"), "MFM": ("澳門", "澳門"), "BKK": ("曼谷", "泰國"),
    "CNX": ("清邁", "泰國"), "HKT": ("普吉島", "泰國"), "SIN": ("新加坡", "新加坡"), "KUL": ("吉隆坡", "馬來西亞"),
    "PEN": ("檳城", "馬來西亞"), "BKI": ("亞庇", "馬來西亞"), "SGN": ("胡志明市", "越南"), "HAN": ("河內", "越南"),
    "DAD": ("峴港", "越南"), "CXR": ("芽莊", "越南"), "PQC": ("富國島", "越南"), "MNL": ("馬尼拉", "菲律賓"),
    "CEB": ("宿霧", "菲律賓"), "CRK": ("克拉克", "菲律賓"), "JKT": ("雅加達", "印尼"), "SUB": ("泗水", "印尼"),
    "DPS": ("峇里島", "印尼"), "PNH": ("金邊", "柬埔寨"), "RGN": ("仰光", "緬甸"), "GUM": ("關島", "關島"),
    "ROR": ("帛琉", "帛琉"), "LAX": ("洛杉磯", "美國"), "SFO": ("舊金山", "美國"), "SEA": ("西雅圖", "美國"),
    "NYC": ("紐約", "美國"), "ONT": ("安大略", "美國"), "DFW": ("達拉斯", "美國"), "IAH": ("休士頓", "美國"),
    "CHI": ("芝加哥", "美國"), "PHX": ("鳳凰城", "美國"), "YVR": ("溫哥華", "加拿大"), "YTO": ("多倫多", "加拿大"),
    "LON": ("倫敦", "英國"), "PAR": ("巴黎", "法國"), "AMS": ("阿姆斯特丹", "荷蘭"), "VIE": ("維也納", "奧地利"),
    "MUC": ("慕尼黑", "德國"), "FRA": ("法蘭克福", "德國"), "PRG": ("布拉格", "捷克"), "MIL": ("米蘭", "義大利"),
    "ROM": ("羅馬", "義大利"), "IST": ("伊斯坦堡", "土耳其"), "DXB": ("杜拜", "阿聯"), "SYD": ("雪梨", "澳洲"),
    "BNE": ("布里斯本", "澳洲"), "MEL": ("墨爾本", "澳洲"), "AKL": ("奧克蘭", "紐西蘭"),
    "TPE": ("台北", "台灣"), "KHH": ("高雄", "台灣"), "RMQ": ("台中", "台灣"),
}

AIRLINES = {
    "BR": "長榮", "CI": "華航", "JX": "星宇", "IT": "台灣虎航", "AE": "華信", "B7": "立榮",
    "MM": "樂桃", "GK": "捷星日本", "3K": "捷星亞洲", "TR": "酷航", "VJ": "越捷", "VZ": "泰越捷",
    "Z2": "菲律賓亞航", "5J": "宿霧太平洋", "ZE": "易斯達", "7C": "濟州航空", "LJ": "真航空",
    "TW": "德威", "RS": "首爾航空", "BX": "釜山航空", "KE": "大韓", "OZ": "韓亞", "NH": "全日空",
    "JL": "日航", "CX": "國泰", "UO": "香港快運", "HX": "香港航空", "NX": "澳門航空", "SQ": "新航",
    "TG": "泰航", "SL": "泰獅航", "FD": "泰亞航", "VN": "越南航空", "PR": "菲航", "D7": "亞航X",
    "AK": "亞航", "MH": "馬航", "OD": "峇迪克", "GA": "印尼航空", "UA": "聯合", "DL": "達美",
    "AA": "美航", "AS": "阿拉斯加", "AC": "加航", "TK": "土航", "EK": "阿聯酋", "KL": "荷航",
    "QF": "澳航", "NZ": "紐航", "BC": "天馬", "VA": "維珍澳洲",
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
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json", **headers}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.status, r.read().decode("utf-8", "ignore")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
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
    return {c: region for region, r in CONFIG["regions"].items() for c in r["cities"]}


def name(code):
    return CITY.get(code, (code, ""))[0]


def country(code):
    return CITY.get(code, ("", code))[1]


def airline_name(code):
    return AIRLINES.get(code, code)


def d_(s):
    return dt.date.fromisoformat(s)


def days_between(a, b):
    return (d_(b) - d_(a)).days


def route_of(f):
    return f"{f['origin']}-{f['dest']}"


# ---------------------------------------------------- 1) Travelpayouts API
def fetch_direct_fares(token):
    c2r = city_to_region()
    fares, errors = [], []
    for origin in CONFIG["origins"]:
        for month in months_ahead(CONFIG["months_ahead"]):
            params = {
                "origin": origin, "departure_at": month, "direct": "true", "sorting": "price",
                "currency": CONFIG["currency"], "one_way": "true" if CONFIG["one_way"] else "false",
                "unique": "false", "limit": 1000, "page": 1,
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
                depart = (t.get("departure_at") or "")[:10]
                if not depart or depart < TODAY_S:
                    continue
                fares.append({
                    "origin": t.get("origin") or origin,
                    "origin_airport": t.get("origin_airport") or origin,
                    "dest": dest,
                    "dest_airport": t.get("destination_airport") or dest,
                    "region": c2r[dest],
                    "price": int(t["price"]),
                    "airline": t.get("airline", ""),
                    "flight": str(t.get("flight_number", "")),
                    "depart": depart,
                    "return": (t.get("return_at") or "")[:10],
                })
    return fares, errors


def skyscanner_link(f):
    def ymd(d):
        return d[2:4] + d[5:7] + d[8:10]
    path = f"{f['origin_airport'].lower()}/{f['dest_airport'].lower()}/{ymd(f['depart'])}/"
    if f["return"]:
        path += f"{ymd(f['return'])}/"
    cabin = "&cabinclass=business" if f.get("cabin") == "business" else ""
    return f"https://www.skyscanner.com.tw/transport/flights/{path}?preferdirects=true{cabin}"


def fetch_business(token):
    """商務艙（trip_class=1）近期價格，只留直飛、監控清單內的目的地。"""
    c2r = city_to_region()
    fares, errors = [], []
    for origin in CONFIG["origins"]:
        params = {
            "origin": origin, "currency": CONFIG["currency"], "period_type": "year",
            "one_way": "true" if CONFIG["one_way"] else "false", "trip_class": 1,
            "sorting": "price", "limit": 1000, "page": 1, "show_to_affiliates": "true",
        }
        url = "https://api.travelpayouts.com/aviasales/v3/get_latest_prices?" + urllib.parse.urlencode(params)
        try:
            payload = json.loads(http_get(url, {"X-Access-Token": token}))
        except Exception as e:  # noqa: BLE001
            errors.append(f"Travelpayouts 商務艙 {origin}: {e}")
            continue
        for t in payload.get("data") or []:
            dest = t.get("destination")
            if dest not in c2r:
                continue
            changes = t.get("number_of_changes", t.get("transfers", 0)) or 0
            if changes != 0 or (t.get("return_transfers") or 0) != 0:
                continue
            if t.get("trip_class") not in (None, 1):
                continue
            depart = (t.get("depart_date") or t.get("departure_at") or "")[:10]
            if not depart or depart < TODAY_S:
                continue
            price = t.get("value") or t.get("price")
            if not price:
                continue
            fares.append({
                "origin": t.get("origin") or origin, "origin_airport": t.get("origin_airport") or origin,
                "dest": dest, "dest_airport": t.get("destination_airport") or dest,
                "region": c2r[dest], "price": int(price), "airline": t.get("airline", "") or "",
                "flight": str(t.get("flight_number", "") or ""), "depart": depart,
                "return": (t.get("return_date") or t.get("return_at") or "")[:10], "cabin": "business",
            })
    return fares, errors


# ------------------------------------------------------- 2) 行程條件篩選
def trip_ok(f):
    """至少 N 天後出發 + 旅行天數符合地區規則。回傳 (是否符合, 天數)。"""
    if days_between(TODAY_S, f["depart"]) < CONFIG["min_days_ahead"]:
        return False, None
    if CONFIG["one_way"] or not f["return"]:
        return True, None
    days = days_between(f["depart"], f["return"]) + 1
    lo, hi = CONFIG["regions"][f["region"]]["trip_days"]
    return lo <= days <= hi, days


# ------------------------------------------- 3) 航線基準價（同航線、同月份）
def group_today(fares):
    groups = {}
    for f in fares:
        groups.setdefault(f"{route_of(f)}|{f['depart'][:7]}", []).append(f["price"])
    return groups


def update_baseline(baseline, groups, keep_days):
    cutoff = (TODAY - dt.timedelta(days=keep_days)).isoformat()
    for key, prices in groups.items():
        rows = [r for r in baseline.get(key, []) if r["d"] != TODAY_S and r["d"] >= cutoff]
        rows.append({"d": TODAY_S, "med": int(statistics.median(prices)), "min": min(prices), "n": len(prices)})
        baseline[key] = rows
    this_month = TODAY_S[:7]
    for key in list(baseline):
        if key.split("|")[1] < this_month:
            del baseline[key]
    return baseline


def baseline_price(key, groups, baseline):
    """回傳 (基準價, 樣本數, 依據)。"""
    route = key.split("|")[0]
    hist = [r["med"] for r in baseline.get(key, []) if r["d"] != TODAY_S]
    hist_n = sum(r["n"] for r in baseline.get(key, []) if r["d"] != TODAY_S)
    today = groups.get(key, [])
    if len(hist) >= LEARN["min_history_days"]:
        pool = hist + ([statistics.median(today)] if len(today) >= 3 else [])
        return statistics.median(pool), hist_n + len(today), "同月歷史"
    if len(today) >= R["min_samples"]:
        return statistics.median(today), len(today), "同月今日"
    all_route = [p for k, v in groups.items() if k.split("|")[0] == route for p in v]
    all_hist = [r["med"] for k, v in baseline.items() if k.split("|")[0] == route for r in v if r["d"] != TODAY_S]
    pool = all_route + all_hist
    if len(pool) >= R["min_samples"]:
        return statistics.median(pool), len(pool), "航線整體"
    return None, len(pool), "樣本不足"


# --------------------------------------------------- 4) 排名 + 錯價判斷
def error_cut_for(route, learning):
    return learning["routes"].get(route, {}).get("cut", LEARN["default_error_cut"])


def rank_deals(fares, groups, baseline, learning):
    """每條航線取降幅最大的一筆（只看符合行程條件的票）。"""
    best = {}
    for f in fares:
        ok, days = trip_ok(f)
        if not ok:
            continue
        key = f"{route_of(f)}|{f['depart'][:7]}"
        base, n, how = baseline_price(key, groups, baseline)
        if not base:
            continue
        drop = 1 - f["price"] / base
        if drop < R["min_drop"]:
            continue
        route = route_of(f)
        cut = error_cut_for(route, learning)
        low_sample = n < R["low_sample_warn"] or how == "航線整體"
        if drop >= cut and not low_sample:
            tag = "🚨疑似錯價"
        elif drop >= R["big_drop"]:
            tag = "🔥大降價"
        else:
            tag = "📉比平常便宜"
        d = {**f, "base": int(base), "drop": drop, "n": n, "how": how, "tag": tag,
             "days": days, "low_sample": low_sample}
        if route not in best or d["drop"] > best[route]["drop"]:
            best[route] = d
    return sorted(best.values(), key=lambda d: -d["drop"])


def evaluate_business(biz, groups, biz_groups, baseline):
    """
    商務艙錯價判斷（兩種訊號，任一成立）：
      1. 價格 ≤ 同航線同月份「經濟艙」一般價 × vs_economy_ratio（商務艙平常約是經濟艙 3–5 倍）
      2. 樣本夠時，比商務艙自己的一般價便宜 error_drop 以上
    """
    best = {}
    for f in biz:
        ok, days = trip_ok(f)
        if not ok:
            continue
        key = f"{route_of(f)}|{f['depart'][:7]}"
        econ, _, _ = baseline_price(key, groups, baseline)
        jbase, jn, _ = baseline_price("J:" + key, biz_groups, baseline)
        reasons = []
        if econ and f["price"] <= econ * BIZ["vs_economy_ratio"]:
            reasons.append(f"只比經濟艙一般價（NT${int(econ):,}）高 {f['price'] / econ - 1:.0%}" if f["price"] > econ
                           else f"比經濟艙一般價（NT${int(econ):,}）還便宜")
        if jbase and jn >= BIZ["min_samples"] and 1 - f["price"] / jbase >= BIZ["error_drop"]:
            reasons.append(f"比商務艙一般價（NT${int(jbase):,}）便宜 {1 - f['price'] / jbase:.0%}")
        if not reasons:
            continue
        d = {**f, "days": days, "econ": int(econ) if econ else None, "jbase": int(jbase) if jbase else None,
             "reasons": reasons, "ratio": f["price"] / econ if econ else 9}
        r = route_of(f)
        if r not in best or d["ratio"] < best[r]["ratio"]:
            best[r] = d
    return sorted(best.values(), key=lambda d: d["ratio"])


def holiday_picks(fares, groups, baseline):
    """每個即將到來的台灣連假（≥3 天），找涵蓋整段連假、最划算的直飛票。"""
    horizon = (TODAY + dt.timedelta(days=31 * CONFIG["months_ahead"])).isoformat()
    soon = (TODAY + dt.timedelta(days=CONFIG["min_days_ahead"])).isoformat()
    blocks = [h for h in HOLIDAYS["taiwan"]
              if h["start"] >= soon and h["start"] <= horizon
              and days_between(h["start"], h["end"]) + 1 >= HF.get("min_block_days", 3)]
    out = []
    for h in blocks[:HF.get("max_holidays", 4)]:
        cands = {}
        for f in fares:
            if not f["return"] or not (f["depart"] <= h["start"] and f["return"] >= h["end"]):
                continue
            ok, days = trip_ok(f)
            if not ok:
                continue
            base, n, how = baseline_price(f"{route_of(f)}|{f['depart'][:7]}", groups, baseline)
            if not base:
                continue
            drop = 1 - f["price"] / base
            if drop < HF.get("min_drop", 0.10):
                continue
            _, leave, _ = holiday_info(f)
            d = {**f, "drop": drop, "base": int(base), "days": days, "leave": leave}
            r = route_of(f)
            if r not in cands or (d["drop"], -d["leave"]) > (cands[r]["drop"], -cands[r]["leave"]):
                cands[r] = d
        picks, used = [], set()
        for d in sorted(cands.values(), key=lambda d: (-d["drop"], d["leave"])):
            c = country(d["dest"])
            if c in used:
                continue
            used.add(c)
            picks.append(d)
            if len(picks) >= HF.get("picks_per_holiday", 2):
                break
        if picks:
            out.append((h, picks))
    return out


def diversify(ranked, top_n):
    """保留長程名額 + 每國/每區上限；不夠再放寬補滿。"""
    picked, by_country, by_region = [], {}, {}

    def can(d):
        return (by_country.get(country(d["dest"]), 0) < DIV["max_per_country"]
                and by_region.get(d["region"], 0) < DIV["max_per_region"])

    def take(d):
        picked.append(d)
        by_country[country(d["dest"])] = by_country.get(country(d["dest"]), 0) + 1
        by_region[d["region"]] = by_region.get(d["region"], 0) + 1

    for d in ranked:  # 配合台灣連假：涵蓋連假的票加分
        d["score"] = d["drop"] + (HF.get("rank_bonus", 0) if holiday_info(d)[0] else 0)
    ranked = sorted(ranked, key=lambda d: -d["score"])
    long_haul = [d for d in ranked if CONFIG["regions"][d["region"]]["long_haul"]]
    for d in long_haul:
        if len(picked) >= DIV["long_haul_slots"]:
            break
        if can(d):
            take(d)
    for d in ranked:  # 錯價一律優先
        if len(picked) >= top_n:
            break
        if d["tag"] == "🚨疑似錯價" and d not in picked:
            take(d)
    for d in ranked:
        if len(picked) >= top_n:
            break
        if d not in picked and can(d):
            take(d)
    for d in ranked:  # 放寬：還不夠 10 筆就補
        if len(picked) >= top_n:
            break
        if d not in picked:
            take(d)
    return sorted(picked, key=lambda d: -d["score"])


# ------------------------------------------------------ 5) 自我檢討（學習）
def review_candidates(learning, fares):
    by_trip = {}
    for f in fares:
        k = f"{route_of(f)}|{f['depart']}|{f['return']}"
        by_trip[k] = min(by_trip.get(k, 10**9), f["price"])
    notes, still_open = [], []
    for c in learning["candidates"]:
        if c["depart"] < TODAY_S:
            continue
        if c["first"] == TODAY_S:
            still_open.append(c)
            continue
        age = days_between(c["first"], TODAY_S)
        now_price = by_trip.get(c["trip"])
        route = c["trip"].split("|")[0]
        rinfo = learning["routes"].setdefault(route, {"cut": LEARN["default_error_cut"], "real": 0, "normal": 0})
        o, de = route.split("-")
        label = f"{name(o)}→{name(de)} NT${c['price']:,}"
        gone = now_price is None or now_price > c["price"] * 1.25
        if gone and age <= LEARN["confirm_days"]:
            rinfo["real"] += 1
            rinfo["cut"] = round(max(LEARN["min_cut"], rinfo["cut"] - LEARN["step_down"]), 3)
            notes.append(f"✅ {label} {age} 天內消失 → 判定真錯價，此航線門檻調為 {rinfo['cut']:.0%}")
        elif not gone and age >= LEARN["persist_days"]:
            rinfo["normal"] += 1
            rinfo["cut"] = round(min(LEARN["max_cut"], rinfo["cut"] + LEARN["step_up"]), 3)
            notes.append(f"🔁 {label} {age} 天後仍在 → 判定淡季/常態低價，此航線門檻提高為 {rinfo['cut']:.0%}")
        elif not gone:
            still_open.append(c)
    learning["candidates"] = still_open
    return notes


def register_candidates(learning, deals):
    tracked = {c["trip"] for c in learning["candidates"]}
    for d in deals:
        if d["tag"] != "🚨疑似錯價":
            continue
        trip = f"{route_of(d)}|{d['depart']}|{d['return']}"
        if trip not in tracked:
            learning["candidates"].append({"trip": trip, "price": d["price"], "base": d["base"],
                                           "depart": d["depart"], "first": TODAY_S})


# ------------------------------------------------- 6) 節日 / 請假天數
def overlaps(a1, a2, b1, b2):
    return a1 <= b2 and b1 <= a2


def holiday_info(d):
    """回傳 (台灣連假名稱清單, 需請假天數, 當地節日清單)。"""
    if not d["return"]:
        return [], None, []
    dep, ret = d["depart"], d["return"]
    tw = [h for h in HOLIDAYS["taiwan"] if overlaps(dep, ret, h["start"], h["end"])]
    off = set()
    for h in HOLIDAYS["taiwan"]:
        day = d_(h["start"])
        while day <= d_(h["end"]):
            off.add(day)
            day += dt.timedelta(days=1)
    leave, day = 0, d_(dep)
    while day <= d_(ret):
        if day.weekday() < 5 and day not in off:
            leave += 1
        day += dt.timedelta(days=1)
    c = country(d["dest"])
    local = [h for h in HOLIDAYS["foreign"] if c in h["countries"] and overlaps(dep, ret, h["start"], h["end"])]
    return [h["name"] for h in tw], leave, local


def lcc_estimate(d):
    if d["airline"] not in LCC["airlines"]:
        return None
    per_leg = LCC["airlines"].get(d["airline"], LCC["default_per_leg"])
    legs = 1 if (CONFIG["one_way"] or not d["return"]) else 2
    add = per_leg * legs
    return add, int(round((d["price"] + add) / 100.0) * 100)


# ------------------------------------------------------ 7) 錯價情報 RSS
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
            if not any(k in text for k in kw):
                continue
            pub = item.findtext("pubDate")
            try:
                when = dt.datetime.strptime(pub[:25].strip(), "%a, %d %b %Y %H:%M:%S").replace(tzinfo=dt.timezone.utc)
                if when < cutoff:
                    continue
            except Exception:  # noqa: BLE001
                pass
            alerts.append({"title": title, "link": link, "error": "error fare" in text or "mistake" in text})
    return alerts, errors


# ------------------------------------------------------------- 8) message
def fmt_date(s):
    return f"{int(s[5:7])}/{int(s[8:10])}"


def deal_lines(i, d):
    trip = "單程" if CONFIG["one_way"] else "來回"
    dates = fmt_date(d["depart"]) + (f"–{fmt_date(d['return'])}" if d["return"] else "")
    days = f"（{d['days']}天）" if d.get("days") else ""
    out = [
        f"{i}. {d['tag']} 便宜 {d['drop']:.0%}",
        f"{name(d['origin'])}→{name(d['dest'])}（{country(d['dest'])}）{trip} NT${d['price']:,}",
        f"此航線{int(d['depart'][5:7])}月一般約 NT${d['base']:,}",
        f"{airline_name(d['airline'])} {d['airline']}{d['flight']} 直飛｜{dates}{days}",
    ]
    if d["low_sample"]:
        out.append(f"⚠️ 樣本少（僅 {d['n']} 筆價格），比較基準可能不準，請多比價")
    lcc = lcc_estimate(d)
    if lcc:
        out.append(f"🧳 廉航不含托運，加 20kg 行李約 +NT${lcc[0]:,} → 約 NT${lcc[1]:,}")
    if PARTY > 1:
        per = lcc[1] if lcc else d["price"]
        out.append(f"👥 {PARTY} 人約 NT${per * PARTY:,}" + ("（含行李）" if lcc else ""))
    tw, leave, local = holiday_info(d)
    if tw:
        out.append(f"🇹🇼 含台灣{ '、'.join(tw) }，只需請假 {leave} 天")
    elif leave is not None:
        out.append(f"🗓 需請假 {leave} 天")
    for h in local[:2]:
        out.append(f"🎌 遇當地{h['name']}：{h['note']}")
    out.append(skyscanner_link(d))
    return out


def biz_lines(d):
    trip = "單程" if CONFIG["one_way"] else "來回"
    dates = fmt_date(d["depart"]) + (f"–{fmt_date(d['return'])}" if d["return"] else "")
    days = f"（{d['days']}天）" if d.get("days") else ""
    al = f"{airline_name(d['airline'])} " if d["airline"] else ""
    out = [f"💼 {name(d['origin'])}→{name(d['dest'])}（{country(d['dest'])}）商務艙{trip} NT${d['price']:,}",
           "・" + "；".join(d["reasons"]),
           f"{al}直飛｜{dates}{days}"]
    tw, leave, _ = holiday_info(d)
    if tw:
        out.append(f"🇹🇼 含台灣{'、'.join(tw)}，只需請假 {leave} 天")
    out.append(skyscanner_link(d))
    return out


def holiday_section(picks):
    lines = ["", "🇹🇼 連假精選（涵蓋整段連假的直飛票）"]
    for h, ds in picks:
        lines.append(f"🎏 {h['name']}（{fmt_date(h['start'])}–{fmt_date(h['end'])}）")
        for d in ds:
            lcc = "（廉航）" if d["airline"] in LCC["airlines"] else ""
            lines.append(f"・{name(d['origin'])}→{name(d['dest'])}（{country(d['dest'])}）NT${d['price']:,}{lcc} 便宜 {d['drop']:.0%}"
                         f"｜{fmt_date(d['depart'])}–{fmt_date(d['return'])} 請假 {d['leave']} 天")
            lines.append(f"  {skyscanner_link(d)}")
    return lines


def holiday_reminder():
    """台灣連假資料快用完時，在日報提醒更新（人事行政總處通常 6 月公布下一年度）。"""
    years = [int(h["start"][:4]) for h in HOLIDAYS["taiwan"]]
    covered = max(years) if years else TODAY.year - 1
    horizon = (TODAY + dt.timedelta(days=31 * CONFIG["months_ahead"])).year
    if covered < horizon or (TODAY.month >= 7 and covered <= TODAY.year):
        return f"📅 提醒：holidays.json 的台灣連假只到 {covered} 年，請找 Claude 更新 {covered + 1} 年連假與國外節日"
    return None


def footer(stats):
    lines = ["", f"📊 已學習 {stats['days']} 天・追蹤 {stats['routes']} 條航線・錯價候選 {stats['open']} 筆"]
    if stats["days"] < LEARN["min_history_days"]:
        lines.append("（前幾天資料較少，基準價會隨天數越來越準）")
    reminder = holiday_reminder()
    if reminder:
        lines += ["", reminder]
    lines += ["", "※ 價格是快取的。點 Skyscanner 連結確認時，價格可能已經變了，這是正常的。"]
    return lines


def build_daily(deals, alerts, notes, errors, stats, biz=None, hpicks=None):
    lo_asia = CONFIG["regions"]["日本"]["trip_days"]
    lines = [f"✈️ 台灣出發直飛機票日報 {TODAY.month}/{TODAY.day}",
             f"條件：{CONFIG['min_days_ahead']} 天後出發｜亞洲 {lo_asia[0]}–{lo_asia[1]} 天｜長程 10 天以上"]
    if deals:
        lines.append(f"降價幅度前 {len(deals)} 名（每條航線跟自己同月份比，分散國家）")
    elif stats.get("repeat"):
        lines.append(f"今天沒有新的降價票（{stats['repeat']} 筆之前已通知過，不重複推播）。")
    else:
        lines.append("今天沒有明顯低於平常價格的直飛票。")
    for i, d in enumerate(deals, 1):
        lines.append("")
        lines += deal_lines(i, d)
    if biz:
        lines += ["", "💼 商務艙錯價"]
        for d in biz:
            lines += biz_lines(d)
    if hpicks:
        lines += holiday_section(hpicks)
    if alerts:
        lines += ["", "📰 錯價情報（Secret Flying）"]
        for a in alerts[:3]:
            lines += [("🚨 " if a["error"] else "• ") + a["title"], a["link"]]
    if notes:
        lines += ["", "🧠 自我檢討"] + notes[:5]
    shown = [e for e in errors if not e.startswith("RSS ")]  # RSS 情報站常擋機器人，只記在 log 不推播
    if shown:
        lines += ["", f"⚠️ {len(shown)} 個資料來源抓取失敗"]
        reasons = {}
        for e in shown:
            r = e.split(": ", 1)[-1][:60]
            reasons[r] = reasons.get(r, 0) + 1
        lines += [f"・{r}（{n} 次）" for r, n in list(reasons.items())[:3]]
    lines += footer(stats)
    return "\n".join(lines).strip()


def build_alert(deals, alerts, biz=None):
    lines = [f"🚨 錯價快報 {dt.datetime.now(TZ):%m/%d %H:%M}", "錯價通常幾小時內就會被修正，有興趣請盡快確認！"]
    for i, d in enumerate(deals, 1):
        lines.append("")
        lines += deal_lines(i, d)
    if biz:
        lines += ["", "💼 商務艙錯價"]
        for d in biz:
            lines += biz_lines(d)
    if alerts:
        lines += ["", "📰 Secret Flying 錯價情報"]
        for a in alerts[:3]:
            lines += ["🚨 " + a["title"], a["link"]]
    lines += ["", "※ 價格是快取的。點 Skyscanner 連結確認時，價格可能已經變了，這是正常的。"]
    return "\n".join(lines).strip()


# ------------------------------------------------------- 9) LINE 卡片（Flex）
TAG_COLOR = {"🚨疑似錯價": "#D32F2F", "🔥大降價": "#EF6C00", "📉比平常便宜": "#00897B"}


def _t(text, size="sm", color="#555555", weight="regular", wrap=True, **kw):
    return {"type": "text", "text": str(text)[:300], "size": size, "color": color, "weight": weight, "wrap": wrap, **kw}


def _btn(label, uri, style="primary", color="#1E88E5"):
    return {"type": "button", "style": style, "height": "sm", "color": color,
            "action": {"type": "uri", "label": label[:20], "uri": uri}}


def _bubble(header_text, header_color, body, buttons):
    return {
        "type": "bubble", "size": "kilo",
        "header": {"type": "box", "layout": "vertical", "backgroundColor": header_color, "paddingAll": "10px",
                   "contents": [_t(header_text, "sm", "#FFFFFF", "bold")]},
        "body": {"type": "box", "layout": "vertical", "spacing": "xs", "paddingAll": "12px", "contents": body},
        "footer": {"type": "box", "layout": "vertical", "spacing": "xs", "paddingAll": "10px", "contents": buttons},
    }


def deal_bubble(i, d):
    trip = "單程" if CONFIG["one_way"] else "來回"
    dates = fmt_date(d["depart"]) + (f"–{fmt_date(d['return'])}" if d["return"] else "")
    days = f"（{d['days']}天）" if d.get("days") else ""
    body = [
        _t(f"{name(d['origin'])} → {name(d['dest'])}", "lg", "#222222", "bold"),
        _t(f"{country(d['dest'])}｜直飛{trip}", "xs", "#888888"),
        _t(f"NT${d['price']:,}", "xxl", TAG_COLOR.get(d["tag"], "#222222"), "bold"),
        _t(f"此航線{int(d['depart'][5:7])}月一般約 NT${d['base']:,}", "xs", "#999999"),
        {"type": "separator", "margin": "md"},
        _t(f"✈️ {airline_name(d['airline'])} {d['airline']}{d['flight']}", "sm", margin="md"),
        _t(f"📅 {dates}{days}"),
    ]
    tw, leave, local = holiday_info(d)
    if tw:
        body.append(_t(f"🇹🇼 含{'、'.join(tw)}，請假 {leave} 天", color="#1565C0", weight="bold"))
    elif leave is not None:
        body.append(_t(f"🗓 需請假 {leave} 天"))
    lcc = lcc_estimate(d)
    if lcc:
        body.append(_t(f"🧳 廉航，加 20kg 行李約 NT${lcc[1]:,}", color="#6D4C41"))
    if PARTY > 1:
        per = lcc[1] if lcc else d["price"]
        body.append(_t(f"👥 {PARTY} 人約 NT${per * PARTY:,}"))
    for h in local[:1]:
        body.append(_t(f"🎌 當地{h['name']}：{h['note']}", "xs", "#AD1457"))
    if d["low_sample"]:
        body.append(_t(f"⚠️ 樣本少（{d['n']} 筆），請多比價", "xs", "#F57C00"))
    return _bubble(f"{i}. {d['tag']}  便宜 {d['drop']:.0%}", TAG_COLOR.get(d["tag"], "#455A64"),
                   body, [_btn("Skyscanner 查看", skyscanner_link(d))])


def biz_bubble(d):
    trip = "單程" if CONFIG["one_way"] else "來回"
    dates = fmt_date(d["depart"]) + (f"–{fmt_date(d['return'])}" if d["return"] else "")
    days = f"（{d['days']}天）" if d.get("days") else ""
    body = [
        _t(f"{name(d['origin'])} → {name(d['dest'])}", "lg", "#222222", "bold"),
        _t(f"{country(d['dest'])}｜商務艙直飛{trip}", "xs", "#888888"),
        _t(f"NT${d['price']:,}", "xxl", "#6A1B9A", "bold"),
    ] + [_t("・" + r, "xs", "#6A1B9A") for r in d["reasons"]] + [
        {"type": "separator", "margin": "md"},
        _t(f"📅 {dates}{days}", margin="md"),
    ]
    tw, leave, _ = holiday_info(d)
    if tw:
        body.append(_t(f"🇹🇼 含{'、'.join(tw)}，請假 {leave} 天", color="#1565C0", weight="bold"))
    return _bubble("💼 商務艙錯價", "#6A1B9A", body, [_btn("Skyscanner 查看", skyscanner_link(d), color="#6A1B9A")])


def holiday_bubble(h, ds):
    body, buttons = [], []
    for d in ds:
        lcc = "（廉航）" if d["airline"] in LCC["airlines"] else ""
        body += [
            _t(f"{name(d['origin'])} → {name(d['dest'])}（{country(d['dest'])}）", "md", "#222222", "bold"),
            _t(f"NT${d['price']:,}{lcc}  便宜 {d['drop']:.0%}", "md", "#1565C0", "bold"),
            _t(f"📅 {fmt_date(d['depart'])}–{fmt_date(d['return'])}｜請假 {d['leave']} 天", "xs", "#666666"),
            {"type": "separator", "margin": "sm"},
        ]
        buttons.append(_btn(f"{name(d['dest'])} 查看", skyscanner_link(d), color="#1565C0"))
    if body and body[-1]["type"] == "separator":
        body.pop()
    return _bubble(f"🇹🇼 {h['name']} {fmt_date(h['start'])}–{fmt_date(h['end'])}", "#1565C0", body, buttons)


def _carousel(alt, bubbles):
    return {"type": "flex", "altText": alt[:400], "contents": {"type": "carousel", "contents": bubbles[:12]}}


def build_daily_flex(deals, alerts, notes, errors, stats, biz, hpicks):
    msgs = []
    if deals:
        head = f"✈️ 機票日報 {TODAY.month}/{TODAY.day}｜降價前 {len(deals)} 名，左右滑動看卡片 👉"
    elif stats.get("repeat"):
        head = f"✈️ 機票日報 {TODAY.month}/{TODAY.day}｜今天沒有新的降價票（{stats['repeat']} 筆之前已通知過）"
    else:
        head = f"✈️ 機票日報 {TODAY.month}/{TODAY.day}｜今天沒有明顯低於平常價格的直飛票"
    msgs.append({"type": "text", "text": head})
    if deals:
        alt = "、".join(f"{name(d['dest'])} NT${d['price']:,}(-{d['drop']:.0%})" for d in deals[:6])
        msgs.append(_carousel(f"今日降價：{alt}", [deal_bubble(i, d) for i, d in enumerate(deals, 1)]))
    extra = [biz_bubble(d) for d in (biz or [])] + [holiday_bubble(h, ds) for h, ds in (hpicks or [])]
    if extra:
        msgs.append(_carousel("商務艙錯價／連假精選", extra))
    tail = []
    if alerts:
        tail += ["📰 錯價情報（Secret Flying）"] + [("🚨 " if a["error"] else "• ") + a["title"] + "\n" + a["link"] for a in alerts[:3]] + [""]
    if notes:
        tail += ["🧠 自我檢討"] + notes[:5] + [""]
    shown = [e for e in errors if not e.startswith("RSS ")]
    if shown:
        tail.append(f"⚠️ {len(shown)} 個資料來源抓取失敗：{shown[0].split(': ', 1)[-1][:60]}")
    tail += [x for x in footer(stats) if x != ""]
    msgs.append({"type": "text", "text": "\n".join(tail).strip()[:4900]})
    return msgs[:5]


def build_alert_flex(deals, alerts, biz):
    msgs = [{"type": "text", "text": f"🚨 錯價快報 {dt.datetime.now(TZ):%m/%d %H:%M}｜錯價通常幾小時內就會被修正，請盡快確認！"}]
    bubbles = [deal_bubble(i, d) for i, d in enumerate(deals, 1)] + [biz_bubble(d) for d in (biz or [])]
    if bubbles:
        alt = "、".join(f"{name(d['dest'])} NT${d['price']:,}" for d in (deals + (biz or []))[:6])
        msgs.append(_carousel(f"錯價：{alt}", bubbles))
    tail = []
    if alerts:
        tail += ["📰 Secret Flying 錯價情報"] + ["🚨 " + a["title"] + "\n" + a["link"] for a in alerts[:3]] + [""]
    tail.append("※ 價格是快取的。點 Skyscanner 連結確認時，價格可能已經變了，這是正常的。")
    msgs.append({"type": "text", "text": "\n".join(tail).strip()})
    return msgs[:5]


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


def send_line(text, flex_messages=None):
    token = "".join((os.environ.get("LINE_CHANNEL_ACCESS_TOKEN") or "").split())
    if not token:
        raise SystemExit("缺少 LINE_CHANNEL_ACCESS_TOKEN")
    # LINE_USER_ID 可放多個，用逗號分隔：個人 U…、群組 C…、多人聊天室 R…
    targets = [t for t in "".join((os.environ.get("LINE_USER_ID") or "").split()).split(",") if t]
    print(f"[LINE 檢查] access token 長度 {len(token)}（正常約 170 以上；32 左右代表貼成 Channel secret）")
    for t in targets:
        kind = {"U": "個人", "C": "群組", "R": "聊天室"}.get(t[:1], "未知")
        ok = t[:1] in "UCR" and len(t) == 33
        print(f"[LINE 檢查] 推播對象：{kind}（{t[:1]}…，{len(t)} 碼）{'✅' if ok else '❌ 應為 U/C/R 開頭 33 碼'}")

    def push_one(target, messages):
        if target:
            body, url = {"to": target, "messages": messages}, "https://api.line.me/v2/bot/message/push"
        else:
            body, url = {"messages": messages}, "https://api.line.me/v2/bot/message/broadcast"
        return http_post_json(url, body, {"Authorization": f"Bearer {token}"})

    def push(messages):
        result = None
        for t in (targets or [None]):
            result = push_one(t, messages)
        return result

    if flex_messages:
        try:
            status, resp = push(flex_messages)
            print(f"LINE（卡片）{status} {resp}")
            send_line.used = "flex"
            return True
        except urllib.error.HTTPError as e:
            if e.code != 400:
                print(f"LINE 推播失敗 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
                return False
            print(f"卡片格式被 LINE 拒收，改用文字版：{e.read().decode('utf-8', 'ignore')[:300]}")
    try:
        status, resp = push([{"type": "text", "text": p} for p in chunk_text(text)])
        print(f"LINE {status} {resp}")
        send_line.used = "text"
        return True
    except urllib.error.HTTPError as e:
        print(f"LINE 推播失敗 HTTP {e.code}: {e.read().decode('utf-8', 'ignore')}")
        if e.code == 401:
            print("→ access token 不對：developers.line.biz/console → channel → Messaging API 分頁最底 → 重新 Issue")
        elif e.code == 400:
            print("→ user ID 不對，或你還沒把官方帳號加為好友")
        return False


# ----------------------------------------------------------------- main
def detect_mode(args):
    """
    回傳 (模式, 是否為自動觸發)。
      MODE=alert       → cron-job.org 錯價快報
      MODE=auto-daily  → cron-job.org 日報（今天送過就跳過）
      GitHub 排程      → 備援日報（今天送過就跳過）
      手動 Run workflow → 日報（一定送）
    """
    mode_in = os.environ.get("MODE", "").strip()
    sched = os.environ.get("EVENT_SCHEDULE", "").strip()
    if "--alert-only" in args or mode_in == "alert":
        return "alert", True
    if mode_in == "auto-daily":
        return "daily", True
    if mode_in == "preview":
        return "preview", False
    if sched:
        return ("daily", True) if sched in CONFIG["alert"]["daily_crons"] else ("alert", True)
    return "daily", False


def main():
    args = set(sys.argv[1:])
    if "--test-line" in args:
        sys.exit(0 if send_line("✅ 機票監控已連上 LINE！") else 1)
    dry = "--dry-run" in args
    mode, auto = detect_mode(args)
    preview = mode == "preview"
    if preview:
        mode = "daily"
    print(f"模式：{'錯價快報' if mode == 'alert' else '每日日報'}{'（自動）' if auto else '（手動）'}")
    state = load_json(STATE_FILE, {})
    if mode == "daily" and auto and state.get("last_daily") == TODAY_S:
        print("今天的日報已經送過了（這是備援排程），不重複推播。")
        return

    token = "".join((os.environ.get("TRAVELPAYOUTS_TOKEN") or "").split())
    errors, fares = [], []
    biz = []
    if token:
        fares, errs = fetch_direct_fares(token)
        errors += errs
        if BIZ.get("enabled"):
            biz, errs = fetch_business(token)
            errors += errs
    else:
        errors.append("缺少 TRAVELPAYOUTS_TOKEN")

    baseline = load_json(BASELINE_FILE, {})
    learning = load_json(LEARN_FILE, {"routes": {}, "candidates": []})
    seen = load_json(SEEN_FILE, {})
    cutoff = (TODAY - dt.timedelta(days=CONFIG["dedupe_days"])).isoformat()
    seen = {k: v for k, v in seen.items() if v >= cutoff}
    if preview:
        print("預覽模式：忽略「已通知過」並且不記錄，可重複看同樣內容")
        seen_saved, seen = seen, {}

    groups = group_today(fares)
    biz_groups = {"J:" + k: v for k, v in group_today(biz).items()}
    notes = review_candidates(learning, fares) if (fares and mode == "daily") else []
    ranked = rank_deals(fares, groups, baseline, learning)

    def key_of(d):
        return f"{route_of(d)}|{d['depart']}|{d['return']}|{d['price']}"

    fresh = [d for d in ranked if key_of(d) not in seen]
    if mode == "alert":
        top = [d for d in fresh if d["tag"] == "🚨疑似錯價"][:R["top_n"]]
    else:
        top = diversify(fresh, R["top_n"])
    for d in top:
        seen[key_of(d)] = TODAY_S
    register_candidates(learning, top)

    biz_top = []
    for d in evaluate_business(biz, groups, biz_groups, baseline):
        k = "J|" + key_of(d)
        if k in seen:
            continue
        biz_top.append(d)
        seen[k] = TODAY_S
        if len(biz_top) >= BIZ.get("max_show", 3):
            break

    hpicks = []
    if mode == "daily":
        for h, ds in holiday_picks(fares, groups, baseline):
            keep = [d for d in ds if "H|" + key_of(d) not in seen]
            for d in keep:
                seen["H|" + key_of(d)] = TODAY_S
            if keep:
                hpicks.append((h, keep))

    alerts, errs = fetch_feed_alerts()
    errors += errs
    fresh_alerts = []
    for a in alerts:
        if mode == "alert" and not a["error"]:
            continue
        k = "rss|" + a["link"]
        if k not in seen:
            fresh_alerts.append(a)
            seen[k] = TODAY_S

    if fares:
        baseline = update_baseline(baseline, {**groups, **biz_groups}, LEARN["keep_days"])
    stats = {
        "days": len({r["d"] for v in baseline.values() for r in v}),
        "routes": len({k.split("|")[0] for k in baseline if not k.startswith("J:")}),
        "open": len(learning["candidates"]),
        "repeat": len(ranked) - len(fresh),
    }
    print(f"抓到 {len(fares)} 筆直飛票價、{len(groups)} 組航線月份、{len(ranked)} 筆符合條件且低於平常、推播 {len(top)} 筆")
    print(f"商務艙 {len(biz)} 筆直飛、錯價 {len(biz_top)} 筆；連假精選 {sum(len(x[1]) for x in hpicks)} 筆")
    run_info = {"at": dt.datetime.now(TZ).isoformat(timespec="minutes"), "mode": mode, "auto": auto,
                "fares": len(fares), "business_fares": len(biz), "ranked": len(ranked), "pushed": len(top),
                "business_errors": len(biz_top), "holiday_picks": sum(len(x[1]) for x in hpicks),
                "errors": [e[:120] for e in errors[:10]]}
    for e in errors:
        print("ERROR:", e)

    if mode == "alert":
        if not top and not fresh_alerts and not biz_top:
            print("沒有新的錯價，不推播。")
            if not dry:
                save_json(BASELINE_FILE, baseline)
                save_json(LEARN_FILE, learning)
                save_json(LAST_RUN_FILE, run_info)
            return
        msg = build_alert(top, fresh_alerts, biz_top)
        flex = build_alert_flex(top, fresh_alerts, biz_top)
    else:
        msg = build_daily(top, fresh_alerts, notes, errors, stats, biz_top, hpicks)
        flex = build_daily_flex(top, fresh_alerts, notes, errors, stats, biz_top, hpicks)
    if CONFIG.get("line_format", "flex") != "flex":
        flex = None
    print("-" * 40)
    print(msg)
    print("-" * 40)
    if dry:
        return

    save_json(BASELINE_FILE, baseline)
    save_json(LEARN_FILE, learning)
    sent = send_line(msg, flex)
    run_info["line_sent"] = sent
    run_info["line_format"] = getattr(send_line, "used", None)
    save_json(LAST_RUN_FILE, run_info)
    if sent and preview:
        pass  # 預覽不寫入已通知紀錄與今日狀態
    elif sent:
        save_json(SEEN_FILE, seen)
        if mode == "daily":
            state["last_daily"] = TODAY_S
            save_json(STATE_FILE, state)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()
