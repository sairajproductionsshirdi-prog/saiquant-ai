# SaiQuant AI — Paper Trading Edition 🙏

Zero-cost AI-assisted paper trading workflow. No API keys, no subscriptions.
The AI (Claude/ChatGPT free chat) analyses; YOU decide; the journal keeps score.

## Setup
    pip install -r requirements.txt

## Daily routine (after market close, or before open)

### Automatic (with ChatGPT API key in .env — costs well under ₹1/day)
1. `python run.py --analyse`
   → snapshot + AI analysis in one step, saved to snapshots/

### Manual fallback (no key needed)
1. `python run.py --snapshot`
   → builds today's indicator snapshot for the watchlist (free NSE data)
2. Open Claude or ChatGPT, paste ANALYST_PROMPT.md + the snapshot
3. Read the analysis. If a setup convinces YOU, log a paper trade:
   `python run.py --buy RELIANCE 2845 3 "AI: strong, SL 2790"`
4. Exit when your stop or target hits:
   `python run.py --sell RELIANCE 2892`
5. `python run.py --report` → win rate, avg win/loss, total paper P&L
6. `python run.py --dashboard` → beautiful web dashboard at http://localhost:8000
   (open http://<laptop-ip>:8000 on your phone via the same WiFi)

## Charts & Android app (PWA)
- `python run.py --dashboard` then open **/charts** — live candlestick charts
  (5-min NSE candles, EMA9/21 overlays, auto-refresh; data ~15 min delayed).
- On Android: open the site in Chrome → menu ⋮ → **Add to Home screen /
  Install app** → SaiQuant AI appears like a real app with its own icon.
- Access from anywhere: deploy free on render.com — this repo already includes
  `wsgi.py` and `render.yaml`, so it deploys as-is.

## The judgment rule
Paper trade for at least 4 weeks / 15+ trades. Go anywhere near real money
ONLY if win-rate × avg-win comfortably beats loss-rate × avg-loss.
If it doesn't — the market just gave you a free lesson. Shraddha & Saburi.

## v7 — Premium edition
- Watchlist groups: 16 blue chips, 20 mid/small caps, 5 multi-baggers,
  plus a Top-10 index strip on the dashboard and index charts.
- `py run.py --analyse --group multibagger` (or bluechip / midsmall / all)
- `py run.py --analyse --group bluechip --intraday` → 15-min candle
  intraday-style analysis (MIS mindset, square-off 15:15)
- AI thinks with 6 lenses incl. celebrity-investor mindset for small caps.
- LIVE TRADING (Zerodha): exists but GATED. live_trading stays false in
  config.yaml until >= 15 closed paper trades. Then: subscribe to Kite
  Connect, add keys to .env, `py run.py --kite-login` daily, and
  `py run.py --live-buy SYMBOL QTY` (typed risk confirmation required).
