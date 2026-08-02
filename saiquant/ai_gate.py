"""
ai_gate.py — The six-lens AI review that stands between a mechanical signal
and a simulated entry.

Design intent:
  The mechanical rules do the cheap wide scan (41 stocks, free data). Only the
  handful that pass get the expensive treatment: full research (fundamentals,
  analyst poll, ownership, news, big-investor activity) and a six-lens AI
  verdict. This keeps API cost to a few rupees a day instead of scanning
  everything with an LLM.

The AI has VETO power and may LOWER conviction, but it may not invent new
trades — every candidate still had to pass the mechanical rules and every
entry still passes the risk engine afterwards. Order of authority:

    mechanical signal  →  AI review (may veto)  →  risk engine (may veto)

Honest limitation (also stated in the README): this layer cannot be
backtested. There are no historical news snapshots, and an LLM reading
today's information about a past date would be contaminated by hindsight.
So its value is a hypothesis being tested forward in paper mode, not a
proven edge.
"""

from __future__ import annotations

import json
import os
import re

import requests

from .research import research_block

MODEL = "gpt-4o-mini"
API_URL = "https://api.openai.com/v1/chat/completions"

GATE_PROMPT = """You are a seasoned, conservative Indian-market trader-analyst \
reviewing ONE candidate trade that has already passed a mechanical technical \
screen. Your job is to APPROVE or REJECT it, thinking through six lenses:

1. SENTIMENT — tone of the provided news: bullish / neutral / bearish. \
Distinguish substance (results, orders, deals) from promotional noise. Flag \
when price action contradicts the news.
2. SMART MONEY — bulk/block deals, stake changes, FII/DII activity, \
ownership. Accumulation is a plus; distribution or promoter selling is a \
warning.
3. EXPERT POLL — analyst consensus and targets. Compare current price to the \
MEAN target: little upside left weakens a long. Note if the street is \
unanimous (crowded) or divided.
4. FUNDAMENTALS — sector, valuation, 52-week position, and EARNINGS \
PROXIMITY. Results within ~7 days is event risk: reject unless the thesis \
is the event.
5. TECHNICALS — is the entry, stop and target sensible given the levels given?
6. CELEBRITY-INVESTOR MINDSET — for small/mid caps: business runway, order \
book momentum, promoter conviction, margin of safety. Would a patient \
long-term investor find this a reasonable place to risk 1% of capital?

Rules:
- Capital protection first. If lenses conflict, REJECT. Rejecting is a \
success, not a failure.
- Use ONLY the data provided. NEVER invent news, deals, investor names or \
ratings. If a field says n/a, treat it as unknown — not as good news.
- No price predictions. Judge setup quality only.
- You may lower the confidence score; you may not raise it above the \
mechanical score.

Respond with ONLY a JSON object, no markdown fences, in this exact shape:
{"decision": "APPROVE" | "REJECT", "confidence": <integer 1-10>, \
"sentiment": "BULLISH" | "NEUTRAL" | "BEARISH", \
"reason": "<= 40 words covering the deciding lenses", \
"risk_note": "<the one thing that would invalidate this trade>"}"""


class AIGateError(Exception):
    pass


def _call_openai(payload_text: str, timeout: int = 45) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise AIGateError("OPENAI_API_KEY not set")
    r = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"},
        json={"model": MODEL, "temperature": 0.2,
              "messages": [{"role": "system", "content": GATE_PROMPT},
                           {"role": "user", "content": payload_text}]},
        timeout=timeout)
    if r.status_code != 200:
        raise AIGateError(f"OpenAI {r.status_code}: {r.text[:160]}")
    return r.json()["choices"][0]["message"]["content"].strip()


def _parse(raw: str) -> dict:
    cleaned = re.sub(r"^```(?:json)?|```$", "", raw.strip(),
                     flags=re.MULTILINE).strip()
    data = json.loads(cleaned)
    decision = str(data.get("decision", "")).upper()
    if decision not in ("APPROVE", "REJECT"):
        raise ValueError(f"bad decision field: {decision!r}")
    conf = int(data.get("confidence", 0))
    return {"decision": decision,
            "confidence": max(1, min(10, conf)),
            "sentiment": str(data.get("sentiment", "NEUTRAL")).upper(),
            "reason": str(data.get("reason", ""))[:300],
            "risk_note": str(data.get("risk_note", ""))[:300]}


def review(signal: dict, group: str, research=research_block,
           call=_call_openai) -> dict:
    """Review one mechanical candidate.

    Returns dict with: approved (bool), confidence (int), sentiment,
    reason, risk_note, and status ('ok' | 'error').

    FAIL-CLOSED: if the AI is unreachable or returns unusable output, the
    trade is REJECTED, not waved through. An unreviewed trade is not a
    reviewed one, and silence is not approval.
    """
    sym = signal["symbol"]
    try:
        ctx = research(sym)
    except Exception as e:
        ctx = f"(research unavailable: {e})"

    payload = (
        f"CANDIDATE: {sym}  (group: {group})\n"
        f"Mechanical signal: entry ₹{signal['price']}, stop ₹{signal['stop']}, "
        f"target ₹{signal['target']}, mechanical confidence "
        f"{signal['confidence']}/10\n"
        f"Technical reasoning: {signal['reason']}\n\n"
        f"RESEARCH:\n{ctx}\n")

    try:
        verdict = _parse(call(payload))
    except (AIGateError, ValueError, KeyError, json.JSONDecodeError) as e:
        return {"approved": False, "confidence": 0, "sentiment": "UNKNOWN",
                "reason": f"AI review unavailable ({str(e)[:80]}) — trade "
                          f"rejected by fail-closed policy",
                "risk_note": "", "status": "error"}

    # AI may lower conviction, never raise it above the mechanical score
    conf = min(verdict["confidence"], signal["confidence"])
    return {"approved": verdict["decision"] == "APPROVE",
            "confidence": conf,
            "sentiment": verdict["sentiment"],
            "reason": verdict["reason"],
            "risk_note": verdict["risk_note"],
            "status": "ok"}
