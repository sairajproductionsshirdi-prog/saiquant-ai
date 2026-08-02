"""
charts.py — Live(ish) candlestick charts + PWA endpoints for SaiQuant AI.

Adds to the dashboard app:
  /charts                 → interactive candlestick page (TradingView
                            lightweight-charts, EMA9/21 overlays, auto-refresh)
  /api/candles/<symbol>   → 5-minute candles JSON (Yahoo Finance, ~15 min delay)
  /manifest.json, /sw.js  → makes the site installable as an Android app (PWA)

Data honesty: Yahoo Finance NSE data is delayed ~15 minutes. Good for paper
trading & analysis. True tick-by-tick live data requires a paid broker feed
(e.g. Kite Connect) — the endpoint here is built so that can be swapped in later.
"""

from __future__ import annotations

import time

import yfinance as yf
from flask import jsonify, render_template_string, Response

from .dashboard import app
from .indicators import ema
from .universe import groups, indices, resolve

_CACHE: dict[str, tuple[float, dict]] = {}
CACHE_SECONDS = 60


def _chart_universe() -> dict:
    """Groups for the chart chips, with indices first."""
    idx = indices()
    out = {"INDICES": list(idx.keys())}
    for g, syms in groups().items():
        out[g.upper()] = syms
    return out, idx


@app.route("/api/candles/<symbol>")
def candles(symbol: str):
    now = time.time()
    if symbol in _CACHE and now - _CACHE[symbol][0] < CACHE_SECONDS:
        return jsonify(_CACHE[symbol][1])

    idx = indices()
    ticker = idx.get(symbol) or resolve(symbol.upper())
    df = yf.Ticker(ticker).history(period="5d", interval="5m")
    if df is None or df.empty:
        return jsonify({"error": f"no data for {symbol}"}), 404

    df = df.reset_index()
    tcol = "Datetime" if "Datetime" in df.columns else df.columns[0]
    e9 = ema(df["Close"], 9)
    e21 = ema(df["Close"], 21)

    def ts(x) -> int:
        return int(x.timestamp())

    payload = {
        "symbol": symbol,
        "candles": [
            {"time": ts(r[tcol]), "open": round(float(r["Open"]), 2),
             "high": round(float(r["High"]), 2), "low": round(float(r["Low"]), 2),
             "close": round(float(r["Close"]), 2)}
            for r in df.to_dict("records")
        ],
        "ema9": [{"time": ts(t), "value": round(float(v), 2)}
                 for t, v in zip(df[tcol], e9)],
        "ema21": [{"time": ts(t), "value": round(float(v), 2)}
                  for t, v in zip(df[tcol], e21)],
        "last": round(float(df["Close"].iloc[-1]), 2),
    }
    _CACHE[symbol] = (now, payload)
    return jsonify(payload)


CHARTS_PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#131A2E">
<title>SaiQuant AI — Charts</title>
<link rel="manifest" href="/manifest.json">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rozha+One&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<script src="https://unpkg.com/lightweight-charts@4.1.3/dist/lightweight-charts.standalone.production.js"></script>
<style>
  :root{--night:#131A2E;--panel:#1B2440;--line:#2A3558;--marigold:#F4A825;
        --ivory:#F5F0E6;--muted:#8B95B5;--gain:#2FBF71;--loss:#E85D4A}
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--night);color:var(--ivory);
       font-family:'IBM Plex Sans',sans-serif}
  .wrap{max-width:1060px;margin:0 auto;padding:16px 14px 40px}
  header{display:flex;align-items:center;justify-content:space-between;
         gap:10px;border-bottom:2px solid var(--marigold);padding-bottom:10px}
  h1{font-family:'Rozha One',serif;font-weight:400;
     font-size:clamp(1.2rem,4vw,1.7rem)}
  h1 .om{color:var(--marigold)}
  a.nav{color:var(--muted);text-decoration:none;font-size:.85rem}
  a.nav:hover{color:var(--marigold)}
  .symbols{display:flex;gap:8px;overflow-x:auto;padding:12px 0;
           -webkit-overflow-scrolling:touch}
  .sym{flex:0 0 auto;background:var(--panel);border:1px solid var(--line);
       color:var(--ivory);border-radius:20px;padding:7px 16px;cursor:pointer;
       font-family:'IBM Plex Mono',monospace;font-size:.82rem}
  .sym.active{border-color:var(--marigold);color:var(--marigold)}
  .price-row{display:flex;align-items:baseline;gap:12px;margin:6px 0 10px}
  #last{font-family:'IBM Plex Mono',monospace;font-size:1.6rem}
  #status{color:var(--muted);font-size:.75rem}
  #chart{height:62vh;min-height:340px;background:var(--panel);
         border:1px solid var(--line);border-radius:10px;overflow:hidden}
  .legend{display:flex;gap:16px;margin-top:8px;color:var(--muted);
          font-size:.78rem;font-family:'IBM Plex Mono',monospace}
  .dot{display:inline-block;width:9px;height:9px;border-radius:50%;
       margin-right:5px;vertical-align:1px}
  footer{margin-top:20px;color:var(--muted);font-size:.75rem;text-align:center}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="om">ॐ</span> SaiQuant AI · Charts</h1>
    <a class="nav" href="/">← Dashboard</a>
  </header>

  <div class="symbols" id="groupTabs" style="padding-bottom:2px"></div>
  <div class="symbols" id="symbols"></div>
  <div class="price-row">
    <div id="last">—</div>
    <div id="status">loading…</div>
  </div>
  <div id="chart"></div>
  <div class="legend">
    <span><span class="dot" style="background:#F4A825"></span>EMA 9</span>
    <span><span class="dot" style="background:#8B95B5"></span>EMA 21</span>
    <span>5-min candles · NSE · ~15 min delayed · auto-refresh 60s</span>
  </div>
  <footer>श्रद्धा · सबुरी — paper trading practice, not financial advice</footer>
</div>

<script>
const UNIVERSE = {{ universe | tojson }};
let currentGroup = Object.keys(UNIVERSE)[1] || Object.keys(UNIVERSE)[0];
let current = UNIVERSE[currentGroup][0],
    chart, candleSeries, ema9Series, ema21Series, timer;

function buildChart(){
  const el = document.getElementById('chart');
  chart = LightweightCharts.createChart(el, {
    layout:{background:{color:'#1B2440'}, textColor:'#8B95B5',
            fontFamily:"'IBM Plex Mono', monospace"},
    grid:{vertLines:{color:'#2A3558'}, horzLines:{color:'#2A3558'}},
    timeScale:{timeVisible:true, secondsVisible:false, borderColor:'#2A3558'},
    rightPriceScale:{borderColor:'#2A3558'},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal},
  });
  candleSeries = chart.addCandlestickSeries({
    upColor:'#2FBF71', downColor:'#E85D4A',
    wickUpColor:'#2FBF71', wickDownColor:'#E85D4A', borderVisible:false});
  ema9Series  = chart.addLineSeries({color:'#F4A825', lineWidth:2,
                                     priceLineVisible:false});
  ema21Series = chart.addLineSeries({color:'#8B95B5', lineWidth:2,
                                     priceLineVisible:false});
  new ResizeObserver(()=>chart.applyOptions(
      {width:el.clientWidth, height:el.clientHeight})).observe(el);
}

async function load(sym){
  document.getElementById('status').textContent = 'loading ' + sym + '…';
  try{
    const r = await fetch('/api/candles/' + encodeURIComponent(sym));
    if(!r.ok) throw new Error('no data');
    const d = await r.json();
    candleSeries.setData(d.candles);
    ema9Series.setData(d.ema9);
    ema21Series.setData(d.ema21);
    const prev = d.candles.length > 1 ? d.candles[d.candles.length-2].close : d.last;
    const el = document.getElementById('last');
    el.textContent = '₹' + d.last.toLocaleString('en-IN');
    el.style.color = d.last >= prev ? '#2FBF71' : '#E85D4A';
    document.getElementById('status').textContent =
      sym + ' · updated ' + new Date().toLocaleTimeString('en-IN');
    chart.timeScale().scrollToRealTime();
  }catch(e){
    document.getElementById('status').textContent =
      sym + ': data unavailable right now (market closed or network issue)';
  }
}

function select(sym){
  current = sym;
  renderChips();
  load(sym);
  clearInterval(timer);
  timer = setInterval(()=>load(current), 60000);
}

function renderChips(){
  const gbar = document.getElementById('groupTabs');
  gbar.innerHTML='';
  Object.keys(UNIVERSE).forEach(g=>{
    const t = document.createElement('button');
    t.className='sym'+(g===currentGroup?' active':'');
    t.style.borderRadius='6px';
    t.textContent=g; t.onclick=()=>{currentGroup=g; renderChips();
      select(UNIVERSE[g][0]);};
    gbar.appendChild(t);
  });
  const bar = document.getElementById('symbols');
  bar.innerHTML='';
  UNIVERSE[currentGroup].forEach(s=>{
    const b = document.createElement('button');
    b.className='sym'+(s===current?' active':'');
    b.textContent=s; b.onclick=()=>select(s);
    bar.appendChild(b);
  });
}
function selectAndRender(sym){ current=sym; renderChips(); }
buildChart();
renderChips();
select(current);
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
</script>
</body>
</html>
"""


@app.route("/charts")
def charts_page():
    uni, _ = _chart_universe()
    return render_template_string(CHARTS_PAGE, universe=uni)


@app.route("/api/overview")
def overview():
    """Index strip: last price + day %change for the top indices."""
    key = "__overview__"
    now = time.time()
    if key in _CACHE and now - _CACHE[key][0] < 120:
        return jsonify(_CACHE[key][1])
    out = []
    for name, ticker in indices().items():
        try:
            h = yf.Ticker(ticker).history(period="5d", interval="1d")
            last, prev = float(h["Close"].iloc[-1]), float(h["Close"].iloc[-2])
            out.append({"name": name,
                        "last": round(last, 1),
                        "chg": round((last - prev) / prev * 100, 2)})
        except Exception:
            out.append({"name": name, "last": None, "chg": None})
    payload = {"indices": out}
    _CACHE[key] = (now, payload)
    return jsonify(payload)


@app.route("/manifest.json")
def manifest():
    return jsonify({
        "name": "SaiQuant AI",
        "short_name": "SaiQuant",
        "start_url": "/",
        "scope": "/",
        "id": "/",
        "display": "standalone",
        "orientation": "portrait",
        "description": "Personal paper-trading dashboard for NSE",
        "background_color": "#131A2E",
        "theme_color": "#131A2E",
        "icons": [
            {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    })


@app.route("/sw.js")
def service_worker():
    # Minimal pass-through service worker: enables "Install app" on Android.
    js = ("self.addEventListener('install',e=>self.skipWaiting());"
          "self.addEventListener('activate',e=>self.clients.claim());"
          "self.addEventListener('fetch',e=>{});")
    return Response(js, mimetype="application/javascript")
