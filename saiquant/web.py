from __future__ import annotations

from html import escape

from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse

from .risk import RiskRejected
from .service import TradingService
from .store import Store
from .strategy import evaluate_sma_volume, sample_bullish_candles

app = FastAPI(title="SaiQuant AI", docs_url=None, redoc_url=None)
store = Store()
service = TradingService(store)


def page(message: str = "") -> str:
    rows = "".join(
        f"<tr><td>{escape(p['symbol'])}</td><td>{p['status']}</td><td>{p['quantity']}</td>"
        f"<td>₹{p['entry']:.2f}</td><td>₹{p['risk']:.2f}</td><td>"
        f"<form method='post' action='/approve/{p['id']}'><button>Approve</button></form> "
        f"<form method='post' action='/reject/{p['id']}'><button class='secondary'>Reject</button></form> "
        f"<form method='post' action='/fill/{p['id']}'><input name='price' value='{p['entry']}' size='7'><button>Simulate</button></form>"
        "</td></tr>" for p in store.list_proposals()
    ) or "<tr><td colspan='6'>No proposals yet.</td></tr>"
    killed = store.is_killed()
    return f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>
    <title>SaiQuant AI</title><style>
    body{{font:16px system-ui;margin:0;background:#f4f6fa;color:#172033}}main{{max-width:1050px;margin:auto;padding:28px}}
    .hero,.card{{background:white;border-radius:16px;padding:22px;margin-bottom:18px;box-shadow:0 5px 20px #17203312}}
    h1{{margin:0;color:#142b55}}.badge{{background:#fff1c7;color:#705400;padding:7px 12px;border-radius:99px}}
    button{{background:#155eef;color:white;border:0;padding:9px 13px;border-radius:8px;cursor:pointer}}button.secondary{{background:#6b7280}}
    button.danger{{background:#c81e1e}}form{{display:inline}}table{{width:100%;border-collapse:collapse}}th,td{{padding:12px;border-bottom:1px solid #e5e7eb;text-align:left}}
    .notice{{padding:12px;background:#eef4ff;border-radius:8px;margin:12px 0}}.limits{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}small{{color:#667085}}
    @media(max-width:700px){{.limits{{grid-template-columns:1fr 1fr}}table{{font-size:12px}}}}
    </style></head><body><main><div class='hero'><span class='badge'>PAPER TRADING ONLY</span><h1>ॐ SaiQuant AI</h1>
    <p>Conservative, rule-based swing-trade proposals with mandatory approval.</p>{f"<div class='notice'>{escape(message)}</div>" if message else ''}
    <form method='post' action='/demo'><button>Load demo opportunity</button></form>
    <form method='post' action='/kill'><button class='danger'>{'Resume bot' if killed else 'STOP BOT'}</button></form></div>
    <div class='card'><h2>Hard limits</h2><div class='limits'><div><b>₹1,00,000</b><br><small>Virtual capital</small></div><div><b>0.25%</b><br><small>Risk/trade</small></div><div><b>5%</b><br><small>Max/stock</small></div><div><b>3</b><br><small>Max positions</small></div></div></div>
    <div class='card'><h2>Trade proposals</h2><table><thead><tr><th>Symbol</th><th>Status</th><th>Qty</th><th>Entry</th><th>Risk</th><th>Manual action</th></tr></thead><tbody>{rows}</tbody></table></div>
    <small>No guaranteed returns. Live Zerodha orders are not implemented in this build.</small></main></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home(message: str = "") -> str:
    return page(message)


def go(message: str) -> RedirectResponse:
    from urllib.parse import quote
    return RedirectResponse(f"/?message={quote(message)}", status_code=303)


@app.post("/demo")
def demo() -> RedirectResponse:
    try:
        signal = evaluate_sma_volume("RELIANCE", "NSE", sample_bullish_candles())
        p = service.propose(signal)
        return go(f"Proposal {p.id} created for {p.quantity} shares. Review before approval.")
    except (ValueError, RiskRejected) as exc:
        return go(str(exc))


@app.post("/approve/{proposal_id}")
def approve(proposal_id: str) -> RedirectResponse:
    try: service.approve(proposal_id); return go("Proposal approved for 15 minutes.")
    except (KeyError, RiskRejected) as exc: return go(str(exc))


@app.post("/reject/{proposal_id}")
def reject(proposal_id: str) -> RedirectResponse:
    try: service.reject(proposal_id); return go("Proposal rejected.")
    except (KeyError, RiskRejected) as exc: return go(str(exc))


@app.post("/fill/{proposal_id}")
def fill(proposal_id: str, price: float = Form(...)) -> RedirectResponse:
    try: service.simulate_fill(proposal_id, price); return go("Paper order simulated successfully. No real order was placed.")
    except (KeyError, RiskRejected) as exc: return go(str(exc))


@app.post("/kill")
def kill() -> RedirectResponse:
    store.set_killed(not store.is_killed())
    return go("Bot state changed. No real positions were affected.")
