"""
research.py — Company research layer: fundamentals + fresh news headlines.

Free sources, no API keys:
  - Fundamentals: Yahoo Finance (sector, market cap, P/E, 52-week range,
    next earnings date when available)
  - News: Google News RSS (last 7 days of headlines per company)

This context is appended to the daily snapshot so the AI analyst can reason
like a professional: technicals for timing, fundamentals for quality,
news for catalysts and risks.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime

import requests
import yfinance as yf

HEADERS = {"User-Agent": "Mozilla/5.0 (SaiQuantAI paper-trading research)"}


def _fmt_crores(value) -> str:
    try:
        return f"₹{value / 1e7:,.0f} Cr"
    except (TypeError, ValueError):
        return "n/a"


def fetch_fundamentals(symbol: str) -> dict:
    """Best-effort fundamentals; missing fields become 'n/a' rather than errors."""
    out = {"sector": "n/a", "market_cap": "n/a", "pe": "n/a",
           "week52_high": "n/a", "week52_low": "n/a", "next_earnings": "n/a"}
    try:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        out["sector"] = info.get("sector") or "n/a"
        out["market_cap"] = _fmt_crores(info.get("marketCap"))
        pe = info.get("trailingPE")
        out["pe"] = round(pe, 1) if isinstance(pe, (int, float)) else "n/a"
        out["week52_high"] = info.get("fiftyTwoWeekHigh", "n/a")
        out["week52_low"] = info.get("fiftyTwoWeekLow", "n/a")
        try:
            cal = t.calendar
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if dates:
                out["next_earnings"] = str(dates[0])[:10]
        except Exception:
            pass
    except Exception:
        pass
    return out


def fetch_news(symbol: str, company_hint: str = "", limit: int = 5) -> list[dict]:
    """Recent headlines from Google News RSS (last 7 days). Best-effort."""
    q = f"{company_hint or symbol} NSE stock when:7d".replace(" ", "+")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        items = []
        for item in root.iter("item"):
            title = (item.findtext("title") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            src = item.find("{https://news.google.com/rss}source")
            source = src.text.strip() if src is not None and src.text else ""
            if not source and " - " in title:
                title, source = title.rsplit(" - ", 1)
            try:
                pub_short = datetime.strptime(
                    pub[:16], "%a, %d %b %Y").strftime("%d %b")
            except ValueError:
                pub_short = pub[:11]
            if title:
                items.append({"title": title, "source": source, "date": pub_short})
            if len(items) >= limit:
                break
        return items
    except Exception:
        return []


def fetch_analyst_poll(symbol: str) -> dict:
    """Street consensus: Yahoo aggregates brokerage analyst ratings & targets."""
    out = {"consensus": "n/a", "analysts": "n/a", "target_mean": "n/a",
           "target_low": "n/a", "target_high": "n/a", "counts": "n/a"}
    try:
        t = yf.Ticker(f"{symbol}.NS")
        info = t.info or {}
        out["consensus"] = (info.get("recommendationKey") or "n/a").replace("_", " ")
        out["analysts"] = info.get("numberOfAnalystOpinions", "n/a")
        for k, key in (("target_mean", "targetMeanPrice"),
                       ("target_low", "targetLowPrice"),
                       ("target_high", "targetHighPrice")):
            v = info.get(key)
            out[k] = round(v, 1) if isinstance(v, (int, float)) else "n/a"
        try:
            rec = t.recommendations_summary
            if rec is not None and len(rec):
                row = rec.iloc[0]
                out["counts"] = (f"strongBuy {row.get('strongBuy', 0)} / "
                                 f"buy {row.get('buy', 0)} / hold {row.get('hold', 0)} / "
                                 f"sell {row.get('sell', 0)} / "
                                 f"strongSell {row.get('strongSell', 0)}")
        except Exception:
            pass
    except Exception:
        pass
    return out


def fetch_smart_money(symbol: str) -> dict:
    """Institutional footprint: insider/institution holding percentages."""
    out = {"holders": "n/a"}
    try:
        t = yf.Ticker(f"{symbol}.NS")
        mh = t.major_holders
        if mh is not None and len(mh):
            try:
                d = {str(i): str(v) for i, v in
                     zip(mh.index.astype(str), mh.iloc[:, 0].astype(str))}
            except Exception:
                d = {str(r[1]): str(r[0]) for r in mh.itertuples(index=False)}
            out["holders"] = "; ".join(f"{k}: {v}" for k, v in list(d.items())[:3])
    except Exception:
        pass
    return out


def fetch_investor_action_news(symbol: str, limit: int = 3) -> list[dict]:
    """Headlines about big-investor activity: bulk/block deals, stake changes,
    FII/DII moves, famous-investor buys."""
    hint = f"{symbol} bulk deal OR block deal OR stake OR FII"
    return fetch_news(symbol, company_hint=hint, limit=limit)


def research_block(symbol: str) -> str:
    """Human/AI-readable research section for one symbol."""
    f = fetch_fundamentals(symbol)
    poll = fetch_analyst_poll(symbol)
    smart = fetch_smart_money(symbol)
    news = fetch_news(symbol)
    action = fetch_investor_action_news(symbol)
    lines = [
        f"Fundamentals: sector {f['sector']} | mcap {f['market_cap']} | "
        f"P/E {f['pe']} | 52w range ₹{f['week52_low']}–₹{f['week52_high']} | "
        f"next earnings: {f['next_earnings']}",
        f"Analyst poll: consensus '{poll['consensus']}' from {poll['analysts']} "
        f"analysts | targets ₹{poll['target_low']} / ₹{poll['target_mean']} / "
        f"₹{poll['target_high']} (low/mean/high) | ratings: {poll['counts']}",
        f"Ownership: {smart['holders']}",
    ]
    if news:
        lines.append("Recent news (7 days):")
        for n in news:
            src = f" [{n['source']}]" if n['source'] else ""
            lines.append(f"  • {n['date']}: {n['title']}{src}")
    else:
        lines.append("Recent news (7 days): none found / fetch failed")
    if action:
        lines.append("Big-investor activity headlines (30 days):")
        for n in action:
            src = f" [{n['source']}]" if n['source'] else ""
            lines.append(f"  • {n['date']}: {n['title']}{src}")
    return "\n".join(lines)
