# SaiQuant AI — Safe Paper-Trading MVP

SaiQuant AI is a conservative swing-trading assistant for Indian cash equities.
This first release is **paper trading only**. It cannot place, modify, or cancel
real Zerodha orders.

## Safety model

1. Daily price candles create a deterministic SMA/volume candidate.
2. The risk engine sizes the trade; AI never controls quantity.
3. A proposal must be manually approved.
4. Approval expires after 15 minutes.
5. Price slippage, position, daily-loss, watchlist, and kill-switch checks run
   again before a simulated fill.

Default limits:

- Virtual capital: ₹1,00,000
- Risk per trade: 0.25%
- Maximum capital per stock: 5%
- Maximum open positions: 3
- Daily loss stop: 1%
- Long-only cash equity; no leverage, F&O, shorting, or averaging down

## Quick start

Python 3.11+ is recommended.

```bash
cd saiquant-ai
python -m venv .venv
source .venv/bin/activate
pip install -e .
uvicorn saiquant.web:app --reload --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000>. Click **Load demo opportunity**, review it,
approve it, and then click **Simulate approved order**.

## Tests

```bash
python -m unittest discover -s tests -v
```

GitHub Actions runs the same six safety tests after every upload or code
change. See `UPLOAD_TO_GITHUB.md` for browser-based upload instructions.

## Configuration

Copy `.env.example` to `.env` only when you later connect read-only Zerodha
data. Never commit `.env`.

The current build uses demo candles and local SQLite storage. The next phase is
read-only Zerodha login and historical/quote ingestion. Live order placement
should be added only after backtesting and 4–8 weeks of paper trading.

## Important

This software is educational and does not provide guaranteed returns or
personalised investment advice. Historical performance does not guarantee
future results.
