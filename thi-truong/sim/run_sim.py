"""Mô phỏng 3 tháng cho trang Market Pulse.

Mô hình:
  1. Mỗi tài sản: GJR-GARCH(1,1), phần dư Student-t lệch (skew-t), trung bình hằng số
     (thu nhỏ về 0 theo drift_shrink). Bắt được cụm biến động, bất đối xứng khi giảm, đuôi dày.
  2. Liên kết giữa các tài sản: Filtered Historical Simulation — rút ngẫu nhiên cả HÀNG
     phần dư chuẩn hoá của cùng một ngày lịch sử, nên tương quan chéo và phụ thuộc đuôi
     được giữ nguyên như trong dữ liệu thật, không cần giả định copula.
  3. Lớp kịch bản: mỗi đường đi rơi vào một kịch bản vĩ mô theo xác suất trong config;
     cú sốc của kịch bản xảy ra một lần vào ngày ngẫu nhiên, độ lớn nhân hệ số ngẫu nhiên.
  4. Kiểm định ngoài mẫu: với nhiều cửa sổ 63 phiên trong quá khứ, fit trên dữ liệu trước
     cửa sổ rồi kiểm tra kết quả thật có rơi vào dải 5–95% hay không.

Chạy:  python run_sim.py            (tải dữ liệu thật)
       python run_sim.py --synthetic (dữ liệu giả để kiểm thử code)
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
from arch import arch_model

HERE = Path(__file__).resolve().parent
OUT = HERE / "sim.json"
QS = [5, 25, 50, 75, 95]


# ---------------------------------------------------------------- dữ liệu
UDF_SOURCES = [
    ("VNDirect", "https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={s}&from={f}&to={t}",
     {"Referer": "https://dchart.vndirect.com.vn/", "Origin": "https://dchart.vndirect.com.vn"}),
    ("VPS", "https://histdatafeed.vps.com.vn/tradingview/history?symbol={s}&resolution=D&from={f}&to={t}",
     {"Referer": "https://banggia.vps.com.vn/", "Origin": "https://banggia.vps.com.vn"}),
    ("SSI", "https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D&symbol={s}&from={f}&to={t}",
     {"Referer": "https://iboard.ssi.com.vn/", "Origin": "https://iboard.ssi.com.vn"}),
]


def _get_json(url, extra):
    h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
         "Accept": "*/*", "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8", **extra}
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_vn_index(symbol, years):
    """Thử lần lượt các API dạng TradingView của công ty chứng khoán VN, rồi TCBS."""
    to = int(time.time())
    frm = to - int(years * 365.25 * 86400)
    errs = []
    for name, tpl, extra in UDF_SOURCES:
        try:
            d = _get_json(tpl.format(s=symbol, f=frm, t=to), extra)
            d = d.get("data", d) if isinstance(d, dict) else d
            if not d.get("t"):
                raise RuntimeError("rỗng")
            idx = pd.to_datetime(pd.Series(d["t"]).astype(int), unit="s").dt.normalize()
            s = pd.Series([float(x) for x in d["c"]], index=idx.values)
            return s, name
        except Exception as e:
            errs.append(f"{name}: {e}")
    try:
        url = (f"https://apipubaws.tcbs.com.vn/stock-insight/v1/stock/bars-long-term?ticker={symbol}"
               f"&type=index&resolution=D&countBack={int(years * 252)}&to={to}")
        d = _get_json(url, {"Referer": "https://tcinvest.tcbs.com.vn/"})
        rows = d["data"]
        idx = pd.to_datetime([r["tradingDate"][:10] for r in rows])
        return pd.Series([float(r["close"]) for r in rows], index=idx), "TCBS"
    except Exception as e:
        errs.append(f"TCBS: {e}")
    raise RuntimeError("; ".join(errs))


def fetch_yahoo(ticker, years):
    import yfinance as yf
    df = yf.download(ticker, period=f"{years}y", interval="1d", auto_adjust=False,
                     progress=False, threads=False)
    if df is None or df.empty:
        raise RuntimeError(f"Yahoo rỗng: {ticker}")
    s = df["Close"]
    if isinstance(s, pd.DataFrame):
        s = s.iloc[:, 0]
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s.dropna().astype(float)


def load_prices(cfg, synthetic=False, assets=None):
    assets = cfg["assets"] if assets is None else assets
    prices, sources, errors = {}, {}, {}
    years = cfg["history_years"]
    if synthetic:
        rng = np.random.default_rng(1)
        idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=int(years * 252))
        common = rng.standard_t(5, size=len(idx)) * 0.006
        for i, a in enumerate(assets):
            vol = 0.008 + 0.002 * i
            r = 0.5 * common + rng.standard_t(4, size=len(idx)) * vol * 0.7
            prices[a["id"]] = pd.Series(100 * np.exp(np.cumsum(r)), index=idx)
            sources[a["id"]] = "synthetic"
        return prices, sources, errors
    for a in assets:
        tries = []
        if a.get("vndirect"):
            tries.append(("VN", lambda a=a: fetch_vn_index(a["vndirect"], years)))
        if a.get("yahoo"):
            tries.append(("Yahoo " + a["yahoo"], lambda a=a: fetch_yahoo(a["yahoo"], years)))
        for label, fn in tries:
            try:
                s = fn()
                if isinstance(s, tuple):
                    s, label = s[0], f"{s[1]} {a.get('vndirect')}"
                if len(s) < 500:
                    raise RuntimeError(f"chỉ có {len(s)} phiên")
                prices[a["id"]], sources[a["id"]] = s, label
                break
            except Exception as e:  # thử nguồn kế tiếp
                errors.setdefault(a["id"], []).append(f"{label}: {e}")
        if a["id"] not in prices:
            print(f"[bỏ qua] {a['id']}: {errors.get(a['id'])}", file=sys.stderr)
    return prices, sources, errors


def align(prices):
    """Đưa mọi chuỗi về lịch ngày làm việc Thứ Hai–Thứ Sáu; ngày nghỉ giữ giá cũ (lợi suất 0)."""
    start = max(s.index.min() for s in prices.values())
    end = max(s.index.max() for s in prices.values())
    cal = pd.bdate_range(start, end)
    df = pd.DataFrame({k: s[~s.index.duplicated(keep="last")] for k, s in prices.items()})
    df = df.reindex(df.index.union(cal)).sort_index().ffill().reindex(cal)
    return df.dropna()


# ---------------------------------------------------------------- mô hình
def fit_garch(r_pct):
    am = arch_model(r_pct, mean="Constant", vol="GARCH", p=1, o=1, q=1, dist="skewt", rescale=False)
    res = am.fit(disp="off", show_warning=False, options={"maxiter": 500})
    p = res.params
    par = dict(mu=float(p["mu"]), omega=float(p["omega"]), alpha=float(p["alpha[1]"]),
               gamma=float(p["gamma[1]"]), beta=float(p["beta[1]"]))
    sig = np.asarray(res.conditional_volatility)
    resid = np.asarray(res.resid)
    z = resid / sig
    last_e, last_s2 = resid[-1], sig[-1] ** 2
    s2_next = par["omega"] + (par["alpha"] + par["gamma"] * (last_e < 0)) * last_e ** 2 + par["beta"] * last_s2
    persist = par["alpha"] + par["gamma"] / 2 + par["beta"]
    lr_var = par["omega"] / (1 - persist) if persist < 0.999 else float(np.var(r_pct))
    return par, z, float(s2_next), float(lr_var), float(persist)


def simulate(params, s2_0, Z, mu_shrink, rng, n_paths, H):
    """Z: ma trận phần dư chuẩn hoá (ngày × tài sản). Rút cả hàng để giữ tương quan.
    Trả về lợi suất log theo ngày, dạng (tài sản, đường, ngày)."""
    k = len(params)
    rows = rng.integers(0, Z.shape[0], size=(n_paths, H))
    out = np.empty((k, n_paths, H))
    for j, p in enumerate(params):
        z = Z[rows, j]
        s2 = np.full(n_paths, s2_0[j])
        mu = p["mu"] * mu_shrink
        for t in range(H):
            e = np.sqrt(s2) * z[:, t]
            out[j, :, t] = (mu + e) / 100.0
            s2 = p["omega"] + (p["alpha"] + p["gamma"] * (e < 0)) * e ** 2 + p["beta"] * s2
    return out


def add_scenarios(logr, ids, sc_cfg, rng):
    k, n, H = logr.shape
    lst = sc_cfg["list"]
    probs = np.array([s["p"] for s in lst], dtype=float)
    probs = probs / probs.sum()
    pick = rng.choice(len(lst), size=n, p=probs)
    day = rng.integers(0, H, size=n)
    lo, hi = sc_cfg.get("shock_scale_range", [1, 1])
    scale = rng.uniform(lo, hi, size=n)
    out = logr.copy()
    for si, s in enumerate(lst):
        m = pick == si
        if not m.any() or not s.get("shock"):
            continue
        for j, aid in enumerate(ids):
            shock = s["shock"].get(aid)
            if shock:
                jump = np.log(np.clip(1 + shock * scale[m], 0.05, None))
                out[j, np.where(m)[0], day[m]] += jump
    return out, pick


def summarize(logr_j, last_price, H):
    cum = np.cumsum(logr_j, axis=1)
    term = np.expm1(cum[:, -1])
    paths = np.exp(np.concatenate([np.zeros((cum.shape[0], 1)), cum], axis=1))
    peak = np.maximum.accumulate(paths, axis=1)
    mdd = (paths / peak - 1).min(axis=1)
    q = np.percentile(term, QS)
    losses = -term
    var95 = np.percentile(losses, 95)
    cvar95 = losses[losses >= var95].mean()
    steps = list(range(0, H + 1, 5))
    if steps[-1] != H:
        steps.append(H)
    fan = np.percentile(paths[:, steps], QS, axis=0) * last_price
    r4 = lambda x: round(float(x), 4)
    return {
        "q": {f"p{p}": r4(v) for p, v in zip(QS, q)},
        "mean": r4(term.mean()),
        "pUp": r4((term > 0).mean()),
        "pDown10": r4((term < -0.10).mean()),
        "pUp10": r4((term > 0.10).mean()),
        "var95": r4(var95), "cvar95": r4(cvar95),
        "mddMedian": r4(np.median(mdd)), "mddP5": r4(np.percentile(mdd, 5)),
        "fan": {"steps": steps, **{f"p{p}": [round(float(v), 4) for v in fan[i]] for i, p in enumerate(QS)}},
    }


def backtest(series_pct, cfg, rng):
    """PIT ngoài mẫu: dải 5–95% có chứa kết quả thật bao nhiêu lần."""
    H, W, nb = cfg["horizon_days"], cfg["fit_window_days"], cfg["backtest_windows"]
    n = len(series_pct)
    hits, pits = 0, []
    for k in range(1, nb + 1):
        origin = n - k * H
        if origin - W < 250:
            break
        train = series_pct[origin - W:origin]
        realized = float(np.expm1(series_pct[origin:origin + H].sum() / 100))
        try:
            par, z, s2, _, _ = fit_garch(train)
        except Exception:
            continue
        sim = simulate([par], [s2], z.reshape(-1, 1), cfg["drift_shrink"], rng, cfg["backtest_paths"], H)[0]
        term = np.expm1(sim.sum(axis=1))
        pit = float((term < realized).mean())
        pits.append(pit)
        lo, hi = np.percentile(term, [5, 95])
        hits += int(lo <= realized <= hi)
    return {"windows": len(pits), "hits90": hits, "pits": [round(p, 3) for p in pits]}


# ---------------------------------------------------------------- chạy
def market_stats(s, kind="price"):
    """Chỉ báo tự tính từ giá đóng cửa thật."""
    s = s.dropna()
    s = s[~s.index.duplicated(keep="last")]
    if kind == "yield" and s.iloc[-1] > 20:
        s = s / 10.0
    last = float(s.iloc[-1])
    def back(n):
        return float(s.iloc[-1 - n]) if len(s) > n else None
    def chg(n):
        b = back(n)
        if b is None or b == 0:
            return None
        return round(last - b, 4) if kind == "yield" else round(last / b - 1, 4)
    prev_year = s[s.index.year < s.index[-1].year]
    ytd = None
    if len(prev_year):
        b = float(prev_year.iloc[-1])
        ytd = round(last - b, 4) if kind == "yield" else round(last / b - 1, 4)
    w = s.tail(252)
    hi, lo = float(w.max()), float(w.min())
    ma50 = float(s.tail(50).mean()); ma200 = float(s.tail(200).mean())
    d = s.diff().tail(14)
    up, dn = d.clip(lower=0).mean(), (-d.clip(upper=0)).mean()
    rsi = 100.0 if dn == 0 else 100 - 100 / (1 + up / dn)
    lr = np.log(s).diff().dropna()
    vol20 = float(lr.tail(20).std() * math.sqrt(252)) if kind != "yield" else None
    if last > ma50 > ma200:
        trend = "up"
    elif last < ma50 < ma200:
        trend = "down"
    else:
        trend = "side"
    spark = s.tail(60).values
    return {
        "kind": kind, "last": round(last, 4), "lastDate": s.index[-1].strftime("%Y-%m-%d"),
        "d1": chg(1), "w1": chg(5), "m1": chg(21), "m3": chg(63), "ytd": ytd,
        "hi52": round(hi, 4), "lo52": round(lo, 4),
        "fromHi": None if kind == "yield" else round(last / hi - 1, 4),
        "ma50": round(ma50, 4), "ma200": round(ma200, 4),
        "aboveMa200": bool(last > ma200), "rsi14": round(float(rsi), 1),
        "vol20": None if vol20 is None else round(vol20, 4), "trend": trend,
        "spark": [round(float(x), 4) for x in spark],
    }


def scenario_fan(logr_j, mask, last, steps):
    cum = np.cumsum(logr_j[mask], axis=1)
    paths = np.exp(np.concatenate([np.zeros((cum.shape[0], 1)), cum], axis=1))
    q = np.percentile(paths[:, steps], [10, 50, 90], axis=0) * last
    return {"p10": [round(float(v), 4) for v in q[0]], "p50": [round(float(v), 4) for v in q[1]],
            "p90": [round(float(v), 4) for v in q[2]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--no-backtest", action="store_true")
    args = ap.parse_args()

    cfg = json.loads((HERE / "config.json").read_text(encoding="utf8"))
    H, N = cfg["horizon_days"], cfg["n_paths"]
    today = dt.date.today()
    rng = np.random.default_rng(cfg["seed_base"] + today.toordinal())

    prices, sources, errors = load_prices(cfg, args.synthetic)
    if len(prices) < 3:
        sys.exit("Không đủ dữ liệu để mô phỏng")
    df = align(prices)
    ids = [a["id"] for a in cfg["assets"] if a["id"] in df.columns]
    meta = {a["id"]: a for a in cfg["assets"]}
    rets = 100 * np.log(df[ids]).diff().dropna()
    fitw = rets.tail(cfg["fit_window_days"])

    params, zs, s2_0, info = [], [], [], {}
    for aid in ids:
        par, z, s2, lrv, persist = fit_garch(fitw[aid].values)
        params.append(par); zs.append(z); s2_0.append(s2)
        info[aid] = {"volNow": round(math.sqrt(s2 * 252) / 100, 4),
                     "volLong": round(math.sqrt(lrv * 252) / 100, 4),
                     "persist": round(persist, 4)}
    Z = np.column_stack(zs)

    pure = simulate(params, s2_0, Z, cfg["drift_shrink"], rng, N, H)
    mixed, pick = add_scenarios(pure, ids, cfg["scenarios"], rng)

    assets_out = []
    for j, aid in enumerate(ids):
        last = float(df[aid].iloc[-1])
        raw_last = prices[aid].index.max().strftime("%Y-%m-%d")
        a = {"id": aid, "name": meta[aid]["name"], "group": meta[aid]["group"],
             "last": round(last, 4), "lastDate": raw_last, "source": sources[aid],
             **info[aid],
             "stat": summarize(pure[j], last, H),
             "scen": summarize(mixed[j], last, H)}
        # kết quả theo từng kịch bản (trung vị)
        a["byScenario"] = {}
        for si, s in enumerate(cfg["scenarios"]["list"]):
            m = pick == si
            if m.any():
                t = np.expm1(mixed[j][m].sum(axis=1))
                a["byScenario"][s["id"]] = {"p50": round(float(np.median(t)), 4),
                                            "p5": round(float(np.percentile(t, 5)), 4),
                                            "p95": round(float(np.percentile(t, 95)), 4),
                                            "pUp": round(float((t > 0).mean()), 4),
                                            "fan": scenario_fan(mixed[j], m, last, a["scen"]["fan"]["steps"])}
        assets_out.append(a)

    # tương quan 60 phiên gần nhất và 5 năm
    corr60 = rets[ids].tail(60).corr().round(2)
    corrL = rets[ids].corr().round(2)

    bt = {}
    if not args.no_backtest:
        brng = np.random.default_rng(cfg["seed_base"])
        tot_w = tot_h = 0
        for aid in ids:
            r = backtest(rets[aid].values, cfg, brng)
            bt[aid] = r
            tot_w += r["windows"]; tot_h += r["hits90"]
        bt["_total"] = {"windows": tot_w, "hits90": tot_h,
                        "rate": round(tot_h / tot_w, 3) if tot_w else None}

    out = {
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "horizonDays": H, "nPaths": N,
        "seed": int(cfg["seed_base"] + today.toordinal()),
        "synthetic": bool(args.synthetic),
        "model": {
            "vol": "GJR-GARCH(1,1), phần dư Student-t lệch, fit trên "
                   f"{len(fitw)} phiên gần nhất",
            "dependence": "Filtered Historical Simulation: rút cả hàng phần dư chuẩn hoá của cùng ngày, "
                          "giữ nguyên tương quan và phụ thuộc đuôi giữa các tài sản",
            "drift": f"Trung bình lịch sử thu nhỏ {int(cfg['drift_shrink'] * 100)}% về 0",
            "calendar": "Ngày làm việc Thứ Hai–Thứ Sáu; ngày nghỉ của từng thị trường coi như lợi suất 0",
        },
        "scenarios": cfg["scenarios"],
        "assets": assets_out,
        "corr60": {"ids": ids, "m": corr60.values.tolist()},
        "corrLong": {"ids": ids, "m": corrL.values.tolist()},
        "backtest": bt,
        "dataErrors": errors,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf8")

    # ---- bảng thị trường tự tính từ dữ liệu thật
    extra = cfg.get("stats_only", [])
    p2, src2, err2 = load_prices(cfg, args.synthetic, extra) if extra else ({}, {}, {})
    allp, allsrc = {**prices, **p2}, {**sources, **src2}
    rows = []
    for a in cfg["assets"] + extra:
        if a["id"] not in allp:
            continue
        try:
            st = market_stats(allp[a["id"]], a.get("kind", "price"))
        except Exception as e:
            err2.setdefault(a["id"], []).append(f"stats: {e}")
            continue
        rows.append({"id": a["id"], "name": a["name"], "group": a["group"], "source": allsrc[a["id"]], **st})
    (HERE / "market.json").write_text(json.dumps({
        "generated": out["generated"], "synthetic": bool(args.synthetic),
        "rows": rows, "dataErrors": {**errors, **err2}}, ensure_ascii=False, separators=(",", ":")), encoding="utf8")
    print(f"Đã ghi market.json · {len(rows)} dòng")
    print(f"Đã ghi {OUT} · {len(ids)} tài sản · {N} đường · H={H}")
    if bt:
        print("Backtest dải 90%:", bt["_total"])


if __name__ == "__main__":
    main()
