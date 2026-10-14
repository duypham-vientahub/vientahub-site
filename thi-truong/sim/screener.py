"""Bộ lọc mã tiềm năng cho Market Pulse (Việt Nam, Mỹ, Crypto).

Đọc danh sách mã và ngưỡng trong screener_config.json, lấy giá ngày thật
(VNDirect/VPS/SSI cho Việt Nam, Yahoo Finance cho Mỹ và crypto), tính bộ lọc
ba tầng theo khung swing MTG của phòng đầu tư rồi ghi screener.json.

  Cổng thị trường: chỉ số chuẩn so với MA50 (có vùng đệm), EMA20, phiên phân phối.
  Tầng 1: thanh khoản trung bình 20 phiên.
  Tầng 2: điểm RS thang 6 = RS 3 tháng dương (2) + RS 6 tháng dương (1)
          + giữ giá khi chỉ số giảm (2) + có mã cùng ngành cùng mạnh (1).
  Tầng 3: U/D volume 50 phiên >= ngưỡng, giá trên MA50.

Chạy: python screener.py            (dữ liệu thật)
      python screener.py --synthetic (dữ liệu giả để thử giao diện)
"""
import argparse
import datetime as dt
import json
import math
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
CFG = HERE / "screener_config.json"
OUT = HERE / "screener.json"

UDF_SOURCES = [
    ("VNDirect", "https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={s}&from={f}&to={t}",
     {"Referer": "https://dchart.vndirect.com.vn/", "Origin": "https://dchart.vndirect.com.vn"}),
    ("VPS", "https://histdatafeed.vps.com.vn/tradingview/history?symbol={s}&resolution=D&from={f}&to={t}",
     {"Referer": "https://banggia.vps.com.vn/", "Origin": "https://banggia.vps.com.vn"}),
    ("SSI", "https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D&symbol={s}&from={f}&to={t}",
     {"Referer": "https://iboard.ssi.com.vn/", "Origin": "https://iboard.ssi.com.vn"}),
]

DEFAULT_RULES = {"n1": 21, "n3": 63, "n6": 126, "holdWin": 25, "hi": 252, "udWin": 50,
                 "baseWin": 15, "near": 0.03, "far": 0.06}
CRYPTO_RULES = {"n1": 30, "n3": 90, "n6": 180, "holdWin": 30, "hi": 365, "near": 0.06, "far": 0.12}


# ---------------------------------------------------------------- dữ liệu
def _get_json(url, extra):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Accept": "*/*", "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8", **extra}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_vn(symbol, days, is_index=False):
    to = int(time.time())
    frm = to - int(days * 1.5 * 86400)
    errs = []
    for name, tpl, extra in UDF_SOURCES:
        try:
            d = _get_json(tpl.format(s=symbol, f=frm, t=to), extra)
            d = d.get("data", d) if isinstance(d, dict) else d
            if not d.get("t"):
                raise RuntimeError("rỗng")
            idx = pd.to_datetime(pd.Series(d["t"]).astype(int), unit="s").dt.normalize().values
            df = pd.DataFrame({"c": [float(x) for x in d["c"]],
                               "v": [float(x or 0) for x in d.get("v", [0] * len(d["c"]))]}, index=idx)
            df = df[~df.index.duplicated(keep="last")].sort_index()
            if not is_index and df["c"].median() > 1000:  # nguồn trả giá theo đồng
                df["c"] = df["c"] / 1000
            return df, name
        except Exception as e:
            errs.append(f"{name}: {e}")
        time.sleep(0.2)
    raise RuntimeError("; ".join(errs))


def fetch_yahoo_batch(tickers, days):
    import yfinance as yf
    out, errs = {}, {}
    period = "2y" if days <= 700 else "5y"
    for i in range(0, len(tickers), 60):
        chunk = tickers[i:i + 60]
        try:
            df = yf.download(chunk, period=period, interval="1d", auto_adjust=True, progress=False,
                             group_by="ticker", threads=True)
        except Exception as e:
            for t in chunk:
                errs[t] = str(e)
            continue
        for t in chunk:
            try:
                sub = df[t] if isinstance(df.columns, pd.MultiIndex) else df
                s = pd.DataFrame({"c": sub["Close"].astype(float), "v": sub["Volume"].astype(float)}).dropna(subset=["c"])
                s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
                if s.empty:
                    raise RuntimeError("rỗng")
                out[t] = s
            except Exception as e:
                errs[t] = f"Yahoo: {e}"
    return out, errs


def synthetic(codes, days, seed):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)
    common = rng.standard_t(5, size=days) * 0.008
    out = {}
    for i, c in enumerate(codes):
        beta = rng.uniform(0.6, 1.4)
        drift = rng.normal(0.0004, 0.0008)
        r = beta * common + rng.standard_t(4, size=days) * rng.uniform(0.01, 0.025) + drift
        px = 20 * (1 + i % 7) * np.exp(np.cumsum(r))
        vol = rng.lognormal(13, 0.5, size=days) * (1 + (r > 0) * rng.uniform(0, 0.6))
        out[c] = pd.DataFrame({"c": px, "v": vol}, index=idx)
    return out


# ---------------------------------------------------------------- chỉ báo
def rnd(x, d=4):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), d)


def ret(c, n):
    return c.iloc[-1] / c.iloc[-1 - n] - 1 if len(c) > n else None


def gate(df, rules, R):
    c, v = df["c"], df["v"]
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
    ema20 = c.ewm(span=20, adjust=False).mean().iloc[-1]
    last = c.iloc[-1]
    line = ma50 * (1 - rules["ma50Buffer"])
    dist = None
    if rules.get("distDown") is not None and v.iloc[-30:].sum() > 0:
        r = c.pct_change()
        d = (r <= -rules["distDown"]) & (v > v.shift(1))
        dist = int(d.iloc[-25:].sum())
    if last < line:
        mode, lv, exp = "Sell Mode", "down", "Không mở lệnh mới"
    elif last < ema20 or (dist is not None and rules.get("distMax") is not None and dist > rules["distMax"]):
        mode, lv, exp = "Wait Mode", "warn", "Chỉ mua rũ bỏ, nửa cỡ lệnh"
    else:
        mode, lv, exp = "Buy Mode", "up", "Được giải ngân theo luật"
    return {"last": rnd(last, 2), "date": c.index[-1].strftime("%Y-%m-%d"), "ma50": rnd(ma50, 2),
            "ma200": rnd(ma200, 2), "ema20": rnd(ema20, 2), "buffer": rules["ma50Buffer"], "line": rnd(line, 2),
            "dist": dist, "distMax": rules.get("distMax"), "mode": mode, "level": lv, "exposure": exp,
            "m1": rnd(ret(c, R["n1"])), "m3": rnd(ret(c, R["n3"])),
            "fromHi": rnd(last / c.iloc[-R["hi"]:].max() - 1)}


def metrics(df, bench, rules, R, value_is_volume):
    j = df.join(bench[["c"]].rename(columns={"c": "b"}), how="inner").dropna(subset=["c", "b"])
    c, v, b = j["c"], j["v"].fillna(0), j["b"]
    if len(c) < R["n6"] + 5:
        raise RuntimeError(f"chỉ có {len(c)} phiên")
    last = c.iloc[-1]
    ema20 = c.ewm(span=20, adjust=False).mean().iloc[-1]
    ma50 = c.rolling(50).mean().iloc[-1]
    ma200 = c.rolling(200).mean().iloc[-1] if len(c) >= 200 else None
    r, rb = c.pct_change(), b.pct_change()
    val = v if value_is_volume else c * v * rules.get("valueMult", 1)
    liq = val.iloc[-20:].mean()
    rs3 = (ret(c, R["n3"]) - ret(b, R["n3"])) * 100
    rs6 = (ret(c, R["n6"]) - ret(b, R["n6"])) * 100
    w = R["holdWin"]
    down = rb.iloc[-w:] < rules["downDay"]
    nd = int(down.sum())
    beat = int((r.iloc[-w:][down] > rb.iloc[-w:][down]).sum())
    exc = float((r.iloc[-w:][down] - rb.iloc[-w:][down]).mean() * 100) if nd else None
    uw = R["udWin"]
    rr, vv = r.iloc[-uw:], v.iloc[-uw:]
    dn = vv[rr < 0].sum()
    ud = vv[rr > 0].sum() / dn if dn > 0 else None
    bw = c.iloc[-R["baseWin"]:]
    base = bw.max() / bw.min() - 1
    hi = c.iloc[-R["hi"]:].max()
    v50 = v.iloc[-50:].mean()
    return {
        "last": rnd(last, 4), "date": c.index[-1].strftime("%Y-%m-%d"),
        "d1": rnd(r.iloc[-1]), "m1": rnd(ret(c, R["n1"])), "m3": rnd(ret(c, R["n3"])),
        "rs3": rnd(rs3, 1), "rs6": rnd(rs6, 1),
        "holdBeat": beat, "holdDays": nd, "holdExc": rnd(exc, 2),
        "ud": rnd(ud, 2), "ema20": rnd(ema20, 4), "ma50": rnd(ma50, 4), "ma200": rnd(ma200, 4),
        "distEma20": rnd(last / ema20 - 1), "fromHi": rnd(last / hi - 1), "hi52": rnd(hi, 4),
        "liq": rnd(liq, 0), "vol14": rnd(r.iloc[-14:].abs().mean() * 100, 2), "base": rnd(base),
        "volRatio5": rnd(v.iloc[-5:].mean() / v50, 2) if v50 > 0 else None,
        "trend": bool(last > ma50 and (ma200 is None or ma50 > ma200)),
        "aboveMa50": bool(last > ma50),
        "spark": [float(f"{x:.4g}") for x in c.iloc[-60:].tolist()],
    }


def score_market(rows, rules, R):
    strong = {}
    for x in rows:
        if x.get("liqOk") and x["rs3"] > 0 and x["rs6"] > 0:
            strong.setdefault(x["sector"], []).append(x["code"])
    for x in rows:
        peers = [p for p in strong.get(x["sector"], []) if p != x["code"]]
        hold_ok = x["holdDays"] >= 3 and x["holdBeat"] / x["holdDays"] >= rules["holdMin"]
        pts = {"rs3": 2 if x["rs3"] > 0 else 0, "rs6": 1 if x["rs6"] > 0 else 0,
               "hold": 2 if hold_ok else 0, "peer": 1 if peers else 0}
        x["pts"] = pts
        x["score"] = sum(pts.values())
        x["peers"] = peers[:4]
        t1 = bool(x["liqOk"])
        t2 = x["score"] >= 4
        t3 = x["ud"] is not None and x["ud"] >= rules["udMin"]
        x["tiers"] = {"t1": t1, "t2": t2, "t3": t3, "trend": x["aboveMa50"]}
        x["pass"] = t1 and t2 and t3 and x["aboveMa50"]
        de, fh = x["distEma20"], x["fromHi"]
        if de > R["far"]:
            x["tag"], x["tagLv"] = "Đã chạy xa EMA20, chờ chỉnh", "warn"
        elif -R["near"] <= de <= R["near"]:
            x["tag"], x["tagLv"] = "Sát EMA20: vùng rũ bỏ", "up"
        elif fh >= -0.03 and x["base"] <= rules["baseMax"]:
            x["tag"], x["tagLv"] = "Sát đỉnh, nền chặt: chờ vượt nền", "up"
        else:
            x["tag"], x["tagLv"] = "Theo dõi", "info"
        if x["ud"] is not None and x["ud"] > rules["udHot"]:
            x["tag"] += " · U/D quá nóng"
    rows.sort(key=lambda x: (not x["pass"], -x["score"], -(x["rs3"] or 0)))
    return rows


def run_market(m, days, syn, seed):
    R = dict(DEFAULT_RULES)
    if m["id"] == "crypto":
        R.update(CRYPTO_RULES)
    R.update({k: v for k, v in m["rules"].items() if k in DEFAULT_RULES})
    rules = m["rules"]
    uni = [u for u in m["universe"] if u["src"] != m["bench"]["src"]]
    errors, data = {}, {}
    if syn:
        data = synthetic([m["bench"]["src"]] + [u["src"] for u in uni], max(days, 300), seed)
        bench = data[m["bench"]["src"]]
    elif m["feed"] == "vn":
        bench, _ = fetch_vn(m["bench"]["src"], days, is_index=True)
        for u in uni:
            try:
                data[u["src"]], _ = fetch_vn(u["src"], days)
            except Exception as e:
                errors[u["code"]] = str(e)[:200]
            time.sleep(0.15)
    else:
        got, errs = fetch_yahoo_batch([m["bench"]["src"]] + [u["src"] for u in uni], days)
        if m["bench"]["src"] not in got:
            raise RuntimeError(f"không lấy được chỉ số chuẩn: {errs.get(m['bench']['src'])}")
        bench = got.pop(m["bench"]["src"])
        data = got
        for u in uni:
            if u["src"] in errs:
                errors[u["code"]] = errs[u["src"]][:200]
    if m.get("valueMult") is None and m["feed"] == "vn":
        rules = {**rules, "valueMult": 1000}
    rows = []
    for u in uni:
        df = data.get(u["src"])
        if df is None:
            errors.setdefault(u["code"], "không có dữ liệu")
            continue
        try:
            x = metrics(df, bench, rules, R, m.get("volumeIsValue", False))
        except Exception as e:
            errors[u["code"]] = str(e)[:200]
            continue
        x.update({"code": u["code"], "sector": u["sector"]})
        x["liqOk"] = x["liq"] is not None and x["liq"] >= rules["minLiq"]
        if not x["liqOk"]:
            x["spark"] = None  # giữ file gọn: chỉ vẽ mã đủ thanh khoản
        rows.append(x)
    rows = score_market(rows, rules, R)
    g = gate(bench, rules, R)
    g.update({"name": m["bench"]["name"]})
    return {
        "id": m["id"], "name": m["name"], "unit": m["unit"], "liqUnit": m["liqUnit"],
        "liqDiv": 1e9 if m["feed"] == "vn" else 1e6,
        "rules": {**{k: v for k, v in rules.items() if k != "valueMult"}, "windows": R},
        "bench": g,
        "counts": {"universe": len(uni), "fetched": len(rows), "liquid": sum(r["liqOk"] for r in rows),
                   "rs": sum(r["liqOk"] and r["score"] >= 4 for r in rows),
                   "pass": sum(r["pass"] for r in rows)},
        "rows": rows, "errors": errors,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    a = ap.parse_args()
    cfg = json.loads(CFG.read_text(encoding="utf8"))
    out = {"generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "synthetic": a.synthetic, "markets": [], "dataErrors": {}}
    for i, m in enumerate(cfg["markets"]):
        try:
            res = run_market(m, cfg["history_days"], a.synthetic, 100 + i)
            out["markets"].append(res)
            print(f"{m['id']}: {res['counts']} · {res['bench']['mode']}")
        except Exception as e:
            out["dataErrors"][m["id"]] = str(e)[:300]
            print(f"[lỗi] {m['id']}: {e}", file=sys.stderr)
    if not out["markets"]:
        print("Không thị trường nào chạy được, giữ nguyên screener.json cũ", file=sys.stderr)
        sys.exit(1)
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf8")


if __name__ == "__main__":
    main()
