"""
dashboard.py — SaiQuant AI local web dashboard.

    python run.py --dashboard

Opens http://localhost:8000 in your browser. On your Android phone
(same WiFi), open http://<your-laptop-ip>:8000 — instant mobile dashboard.

Reads the paper journal (SQLite) and the latest AI analysis from snapshots/.
Server-side rendered; refresh the page to update.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from flask import Flask, render_template_string

from .paperbook import PaperBook

SNAP_DIR = Path(__file__).resolve().parent.parent / "snapshots"

app = Flask(__name__)

PAGE = r"""
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SaiQuant AI — Paper Trading</title>
<meta name="theme-color" content="#131A2E">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="SaiQuant AI">
<link rel="manifest" href="/manifest.json">
<link rel="icon" href="/static/favicon.png">
<link rel="apple-touch-icon" href="/static/icon-192.png">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Rozha+One&family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root{
    --night:#131A2E; --panel:#1B2440; --line:#2A3558;
    --marigold:#F4A825; --ivory:#F5F0E6; --muted:#8B95B5;
    --gain:#2FBF71; --loss:#E85D4A;
  }
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:var(--night);color:var(--ivory);
       font-family:'IBM Plex Sans',sans-serif;min-height:100vh}
  .wrap{max-width:1060px;margin:0 auto;padding:28px 20px 60px}

  header{display:flex;align-items:baseline;justify-content:space-between;
         flex-wrap:wrap;gap:8px;border-bottom:2px solid var(--marigold);
         padding-bottom:14px}
  h1{font-family:'Rozha One',serif;font-size:clamp(1.6rem,4vw,2.3rem);
     font-weight:400;letter-spacing:.5px}
  h1 .om{color:var(--marigold)}
  .meta{color:var(--muted);font-size:.85rem}
  .badge{display:inline-block;border:1px solid var(--marigold);
         color:var(--marigold);border-radius:3px;padding:2px 8px;
         font-family:'IBM Plex Mono',monospace;font-size:.72rem;
         letter-spacing:.12em;margin-left:8px;vertical-align:2px}

  /* signature: the P&L diya */
  .diya{margin:26px 0;background:var(--panel);border:1px solid var(--marigold);
        border-radius:10px;padding:26px 22px;text-align:center;
        box-shadow:0 0 34px rgba(244,168,37,.13)}
  .diya .label{color:var(--muted);font-size:.78rem;letter-spacing:.22em;
               text-transform:uppercase}
  .diya .value{font-family:'IBM Plex Mono',monospace;
               font-size:clamp(2.2rem,7vw,3.4rem);font-weight:500;margin-top:6px}
  .gain{color:var(--gain)} .loss{color:var(--loss)}

  .stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));
         gap:12px;margin-bottom:26px}
  .stat{background:var(--panel);border:1px solid var(--line);border-radius:8px;
        padding:14px 16px}
  .stat .k{color:var(--muted);font-size:.72rem;letter-spacing:.14em;
           text-transform:uppercase}
  .stat .v{font-family:'IBM Plex Mono',monospace;font-size:1.25rem;margin-top:4px}

  h2{font-family:'Rozha One',serif;font-weight:400;font-size:1.15rem;
     color:var(--marigold);margin:26px 0 10px}
  table{width:100%;border-collapse:collapse;background:var(--panel);
        border:1px solid var(--line);border-radius:8px;overflow:hidden;
        font-size:.88rem}
  th{color:var(--muted);font-weight:500;text-align:left;font-size:.72rem;
     letter-spacing:.12em;text-transform:uppercase;padding:10px 12px;
     border-bottom:1px solid var(--line)}
  td{padding:9px 12px;border-bottom:1px solid var(--line);
     font-family:'IBM Plex Mono',monospace}
  tr:last-child td{border-bottom:none}
  td.note{font-family:'IBM Plex Sans',sans-serif;color:var(--muted)}
  .empty{color:var(--muted);background:var(--panel);border:1px dashed var(--line);
         border-radius:8px;padding:18px;font-size:.88rem}

  pre.analysis{background:var(--panel);border:1px solid var(--line);
      border-left:3px solid var(--marigold);border-radius:8px;padding:16px;
      white-space:pre-wrap;font-family:'IBM Plex Mono',monospace;
      font-size:.8rem;line-height:1.55;color:var(--ivory)}

  .idx-strip{display:flex;gap:10px;overflow-x:auto;margin-top:16px;
             padding-bottom:4px;-webkit-overflow-scrolling:touch}
  .idx{flex:0 0 auto;background:var(--panel);border:1px solid var(--line);
       border-radius:8px;padding:10px 14px;min-width:132px}
  .idx .n{color:var(--muted);font-size:.65rem;letter-spacing:.1em;
          text-transform:uppercase;white-space:nowrap}
  .idx .p{font-family:'IBM Plex Mono',monospace;font-size:1rem;margin-top:3px}
  .idx .c{font-family:'IBM Plex Mono',monospace;font-size:.75rem}
  .cmd{background:var(--panel);border:1px solid var(--line);border-radius:8px;
       padding:14px;display:flex;flex-direction:column;gap:10px}
  .cmd-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
  .cmd input,.cmd select{background:var(--night);border:1px solid var(--line);
       color:var(--ivory);border-radius:6px;padding:8px 10px;
       font-family:'IBM Plex Mono',monospace;font-size:.82rem;flex:1;min-width:90px}
  .chk{color:var(--muted);font-size:.8rem;display:flex;gap:5px;align-items:center;flex:0}
  .btn{background:var(--marigold);color:#131A2E;border:none;border-radius:6px;
       padding:9px 16px;font-weight:600;cursor:pointer;font-size:.82rem;flex:0}
  .btn.buy{background:var(--gain);color:#fff}
  .btn.sell{background:var(--loss);color:#fff}
  .btn:disabled{opacity:.5}
  .cmdout{font-family:'IBM Plex Mono',monospace;font-size:.78rem;
          white-space:pre-wrap;color:var(--muted);max-height:300px;overflow:auto}
  footer{margin-top:38px;text-align:center;color:var(--muted);font-size:.8rem}
  footer b{color:var(--marigold);font-weight:500}
  @media (prefers-reduced-motion:no-preference){
    .diya{transition:box-shadow .4s}
    .diya:hover{box-shadow:0 0 46px rgba(244,168,37,.22)}
  }
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1><span class="om">ॐ</span> SaiQuant AI<span class="badge">PAPER MODE</span></h1>
    <div class="meta"><a href="/charts" style="color:var(--marigold);text-decoration:none">📈 Charts</a> · {{ today }} · refresh page to update</div>
  </header>

  <div class="idx-strip" id="idxStrip"></div>

  <div class="diya">
    <div class="label">Total paper P&amp;L</div>
    <div class="value {{ 'gain' if stats.total_pnl >= 0 else 'loss' }}">
      ₹{{ '{:,.0f}'.format(stats.total_pnl) }}
    </div>
  </div>

  <div class="stats">
    <div class="stat"><div class="k">Trades closed</div><div class="v">{{ stats.trades }}</div></div>
    <div class="stat"><div class="k">Win rate</div><div class="v">{{ stats.win_rate }}%</div></div>
    <div class="stat"><div class="k">Avg win</div><div class="v gain">₹{{ '{:,.0f}'.format(stats.avg_win) }}</div></div>
    <div class="stat"><div class="k">Avg loss</div><div class="v loss">₹{{ '{:,.0f}'.format(stats.avg_loss) }}</div></div>
  </div>

  <h2>Open positions</h2>
  {% if open_pos %}
  <table>
    <tr><th>Symbol</th><th>Qty</th><th>Entry ₹</th><th>Opened</th><th>Note</th></tr>
    {% for p in open_pos %}
    <tr><td>{{ p[0] }}</td><td>{{ p[1] }}</td><td>{{ p[2] }}</td>
        <td>{{ p[3][:16] }}</td><td class="note">{{ p[4] }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">No open positions. Log one with:
    <code>python run.py --buy SYMBOL PRICE QTY "note"</code></div>{% endif %}

  <h2>Closed trades</h2>
  {% if closed %}
  <table>
    <tr><th>Symbol</th><th>Qty</th><th>Entry</th><th>Exit</th><th>P&amp;L ₹</th><th>Closed</th><th>Note</th></tr>
    {% for t in closed %}
    <tr><td>{{ t[0] }}</td><td>{{ t[1] }}</td><td>{{ t[2] }}</td><td>{{ t[3] }}</td>
        <td class="{{ 'gain' if t[4] >= 0 else 'loss' }}">{{ '{:,.0f}'.format(t[4]) }}</td>
        <td>{{ t[6][:16] }}</td><td class="note">{{ t[7] }}</td></tr>
    {% endfor %}
  </table>
  {% else %}<div class="empty">No closed trades yet. The scorecard begins with your first exit.</div>{% endif %}

  <h2>🤖 Autonomous campaign <span class="meta" id="campDay"></span></h2>
  <div class="stats" id="campStats"><div class="stat"><div class="k">status</div>
    <div class="v">loading…</div></div></div>

  <h2>⚡ Command center</h2>
  <div class="cmd">
    <input type="password" id="pw" placeholder="Action password">
    <div class="cmd-row">
      <select id="grp">
        <option value="multibagger">Multibagger</option>
        <option value="bluechip">Bluechip</option>
        <option value="midsmall">Mid/Small</option>
        <option value="all">All (slow)</option>
      </select>
      <label class="chk"><input type="checkbox" id="intra"> Intraday</label>
      <button class="btn" onclick="runAnalyse()">Run AI analysis</button>
      <button class="btn" onclick="runAuto()">Run auto cycle</button>
    </div>
    <div class="cmd-row">
      <select id="btgrp">
        <option value="multibagger">Multibagger</option>
        <option value="bluechip">Bluechip</option>
        <option value="midsmall">Mid/Small</option>
        <option value="all">All (slow)</option>
      </select>
      <input id="btyears" type="number" value="3" min="1" max="10" style="width:70px" title="years">
      <input id="btstop" type="number" value="5" step="0.5" style="width:70px" title="stop %">
      <input id="bttarget" type="number" value="12" step="0.5" style="width:70px" title="target %">
      <button class="btn" onclick="runBacktest()">Backtest history</button>
    </div>
    <div class="cmd-row">
      <input id="tsym" placeholder="SYMBOL" style="width:110px">
      <input id="tprice" placeholder="Price" type="number" step="0.05" style="width:90px">
      <input id="tqty" placeholder="Qty" type="number" style="width:70px">
      <input id="tnote" placeholder="Note (e.g. AI strong, SL 2790)">
      <button class="btn buy" onclick="trade('BUY')">Paper BUY</button>
      <button class="btn sell" onclick="trade('SELL')">Paper SELL</button>
    </div>
    <div id="cmdout" class="cmdout"></div>
  </div>

  <h2>Latest AI analysis {% if analysis_date %}<span class="meta">({{ analysis_date }})</span>{% endif %}</h2>
  {% if analysis %}<pre class="analysis">{{ analysis }}</pre>
  {% else %}<div class="empty">No analysis yet today. Run:
    <code>python run.py --analyse</code></div>{% endif %}

  <footer>श्रद्धा · सबुरी — <b>Shraddha &amp; Saburi</b> · paper trading practice, not financial advice</footer>
</div>
<script>
function out(msg, ok){ const o=document.getElementById('cmdout');
  o.style.color = ok ? '#2FBF71' : '#E85D4A'; o.textContent = msg; }
async function post(url, body){
  body.password = document.getElementById('pw').value;
  const r = await fetch(url,{method:'POST',
    headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let d; try{ d = await r.json(); }
  catch(e){ d = {error:'Server busy or waking up — wait 30s and try again.'}; }
  return [r.ok, d];
}
async function getJSON(url){
  const r = await fetch(url);
  try{ return [r.ok, await r.json()]; }
  catch(e){ return [false, {error:'server busy'}]; }
}
function pollJob(job, label){
  const btns=document.querySelectorAll('.btn'); let ticks=0;
  const poll = setInterval(async ()=>{
    ticks++;
    const [rok, rd] = await getJSON('/api/action/result/'+job);
    if(rd.state === 'running' || !rok){
      out('⏳ ' + (rd.status || label) + ' (' + (ticks*5) + 's)', true);
      if(ticks > 120){ clearInterval(poll);
        out('Taking unusually long — refresh in a minute and try a smaller group.', false);
        btns.forEach(b=>b.disabled=false); }
      return;
    }
    clearInterval(poll);
    if(rd.state === 'done') out(rd.report, true); else out(rd.error, false);
    btns.forEach(b=>b.disabled=false);
  }, 5000);
}
async function runBacktest(){
  const btns=document.querySelectorAll('.btn'); btns.forEach(b=>b.disabled=true);
  out('Starting backtest…', true);
  try{
    const [ok,d] = await post('/api/action/backtest', {
      group:document.getElementById('btgrp').value,
      years:document.getElementById('btyears').value,
      stop:document.getElementById('btstop').value,
      target:document.getElementById('bttarget').value});
    if(!ok){ out(d.error, false); btns.forEach(b=>b.disabled=false); return; }
    pollJob(d.job_id, 'backtesting…');
  }catch(e){ out('Network error: '+e, false); btns.forEach(b=>b.disabled=false); }
}
async function runAuto(){
  const btns=document.querySelectorAll('.btn'); btns.forEach(b=>b.disabled=true);
  out('Starting autonomous paper cycle…', true);
  try{
    const [ok,d] = await post('/api/action/auto', {});
    if(!ok){ out(d.error, false); btns.forEach(b=>b.disabled=false); return; }
    pollJob(d.job_id, 'running cycle…');
  }catch(e){ out('Network error: '+e, false); btns.forEach(b=>b.disabled=false); }
}
async function runAnalyse(){
  const btns=document.querySelectorAll('.btn'); btns.forEach(b=>b.disabled=true);
  out('Starting analysis job…', true);
  try{
    const [ok,d] = await post('/api/action/analyse',
      {group:document.getElementById('grp').value,
       intraday:document.getElementById('intra').checked});
    if(!ok){ out(d.error, false); btns.forEach(b=>b.disabled=false); return; }
    pollJob(d.job_id, 'analysing…');
  }catch(e){ out('Network error: '+e, false); btns.forEach(b=>b.disabled=false); }
}
async function trade(side){
  const body={side, symbol:document.getElementById('tsym').value,
    price:document.getElementById('tprice').value,
    qty:document.getElementById('tqty').value,
    note:document.getElementById('tnote').value};
  try{
    const [ok,d] = await post('/api/action/trade', body);
    if(ok){ out(d.ok, true); setTimeout(()=>location.reload(), 1200); }
    else out(d.error, false);
  }catch(e){ out('Network error: '+e, false); }
}
if('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');
fetch('/api/campaign').then(r=>r.json()).then(c=>{
  const box = document.getElementById('campStats');
  if(!c.active){ box.innerHTML='<div class="stat"><div class="k">campaign</div>'+
    '<div class="v">not started — tap “Run auto cycle”</div></div>'; return; }
  document.getElementById('campDay').textContent =
    '(day '+c.day+' of 15 · paper only · '+(c.storage||'')+')';
  const b = c.benchmark && c.benchmark.available ? c.benchmark.return_pct : null;
  const cards = [
    ['Equity', '₹'+Math.round(c.final_equity).toLocaleString('en-IN')],
    ['Return', (c.return_pct>=0?'+':'')+c.return_pct+'%'],
    ['Nifty B&H', b===null?'—':((b>=0?'+':'')+b+'%')],
    ['Closed trades', c.trades||0],
    ['Win rate', (c.win_rate||0)+'%'],
    ['Max DD', c.max_drawdown_pct+'%'],
    ['Sharpe', c.sharpe===null?'—':c.sharpe],
    ['Open', c.open_positions]];
  box.innerHTML = cards.map(([k,v])=>'<div class="stat"><div class="k">'+k+
    '</div><div class="v">'+v+'</div></div>').join('');
}).catch(()=>{});
fetch('/api/overview').then(r=>r.json()).then(d=>{
  const s = document.getElementById('idxStrip');
  d.indices.forEach(i=>{
    const el = document.createElement('div');
    el.className='idx';
    const up = i.chg !== null && i.chg >= 0;
    el.innerHTML = '<div class="n">'+i.name+'</div>'+
      '<div class="p">'+(i.last===null?'—':i.last.toLocaleString('en-IN'))+'</div>'+
      '<div class="c" style="color:'+(i.chg===null?'#8B95B5':(up?'#2FBF71':'#E85D4A'))+'">'+
      (i.chg===null?'':((up?'▲ +':'▼ ')+i.chg+'%'))+'</div>';
    s.appendChild(el);
  });
}).catch(()=>{});
</script>
</body>
</html>
"""


def _latest_analysis() -> tuple[str | None, str | None]:
    if not SNAP_DIR.exists():
        return None, None
    files = sorted(SNAP_DIR.glob("analysis_*.txt"))
    if not files:
        return None, None
    f = files[-1]
    return f.read_text(encoding="utf-8"), f.stem.replace("analysis_", "")


@app.route("/")
def home():
    book = PaperBook()
    text, adate = _latest_analysis()
    stats = book.stats()

    class S:  # attribute access in template
        pass
    s = S()
    for k, v in stats.items():
        setattr(s, k, v)

    return render_template_string(
        PAGE,
        today=date.today().strftime("%d %b %Y"),
        stats=s,
        open_pos=book.open_positions(),
        closed=book.closed_trades(),
        analysis=text,
        analysis_date=adate,
    )


def serve(port: int = 8000) -> None:
    from . import charts   # noqa: F401 — registers /charts and API routes
    from . import actions  # noqa: F401 — registers web-command routes
    import socket
    try:
        ip = socket.gethostbyname(socket.gethostname())
    except OSError:
        ip = "your-laptop-ip"
    print(f"\n🕉  SaiQuant AI dashboard:")
    print(f"   This computer : http://localhost:{port}")
    print(f"   Phone (same WiFi): http://{ip}:{port}")
    print("   Press Ctrl+C to stop.\n")
    app.run(host="0.0.0.0", port=port, debug=False)
