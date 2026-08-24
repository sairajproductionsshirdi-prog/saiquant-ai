#!/usr/bin/env python3
"""
SaiQuant AI — Paper Trading Edition (₹0/month, no API keys)

Daily workflow:
  python run.py --snapshot        # build today's market snapshot (also saved to snapshots/)
  → paste ANALYST_PROMPT.md + snapshot into Claude/ChatGPT
  python run.py --buy RELIANCE 2845 3 "AI: strong, SL 2790"
  python run.py --sell RELIANCE 2892
  python run.py --report          # positions, closed trades, win-rate stats
"""

import argparse
from datetime import date, datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

console = Console()


def main() -> None:
    load_dotenv()
    cfg = yaml.safe_load(open(Path(__file__).parent / "config.yaml", encoding="utf-8"))

    ap = argparse.ArgumentParser(description="SaiQuant AI paper trading")
    ap.add_argument("--snapshot", action="store_true")
    ap.add_argument("--analyse", action="store_true",
                    help="snapshot + ChatGPT API analysis in one step")
    ap.add_argument("--group", default="bluechip",
                    choices=["bluechip", "midsmall", "multibagger", "all"],
                    help="which watchlist group to analyse (default bluechip)")
    ap.add_argument("--intraday", action="store_true",
                    help="intraday mode: 15-min candles, MIS-style analysis")
    ap.add_argument("--buy", nargs="+", metavar=("SYMBOL PRICE QTY [NOTE]"))
    ap.add_argument("--sell", nargs=2, metavar=("SYMBOL", "PRICE"))
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--auto", action="store_true",
                    help="run one autonomous paper-trading cycle (PAPER ONLY)")
    ap.add_argument("--live-paper", action="store_true",
                    help="LIVE market paper trading loop (9:15-15:30, PAPER only)")
    ap.add_argument("--poll", type=int, default=5,
                    help="minutes between live-paper checks (default 5)")
    ap.add_argument("--no-ai", action="store_true",
                    help="run the auto cycle on mechanical rules only")
    ap.add_argument("--reset-campaign", action="store_true",
                    help="WIPE the campaign and start fresh (asks to confirm)")
    ap.add_argument("--campaign", action="store_true",
                    help="campaign status: equity, positions, metrics")
    ap.add_argument("--final-report", action="store_true",
                    help="full 15-day performance report and verdict")
    ap.add_argument("--decisions", type=int, default=0, metavar="N",
                    help="show last N logged decisions with reasons")
    ap.add_argument("--backtest", action="store_true",
                    help="test the mechanical strategy on historical data")
    ap.add_argument("--years", type=int, default=3,
                    help="years of history for --backtest (default 3)")
    ap.add_argument("--stop", type=float, default=5.0,
                    help="stop-loss %% for backtest (default 5)")
    ap.add_argument("--target", type=float, default=12.0,
                    help="target %% for backtest (default 12)")
    ap.add_argument("--kite-login", action="store_true",
                    help="daily Zerodha Kite login (live trading)")
    ap.add_argument("--live-buy", nargs=2, metavar=("SYMBOL", "QTY"),
                    help="REAL order via Zerodha (gated)")
    ap.add_argument("--live-sell", nargs=2, metavar=("SYMBOL", "QTY"),
                    help="REAL order via Zerodha (gated)")
    ap.add_argument("--dashboard", action="store_true",
                    help="open the web dashboard at http://localhost:8000")
    args = ap.parse_args()

    if args.analyse:
        from saiquant.snapshot import build_snapshot
        from saiquant.ai_analyst import analyse, save_analysis, AIAnalystError
        from saiquant.universe import groups, all_symbols
        syms = all_symbols() if args.group == "all" else groups()[args.group]
        interval = "15m" if (args.intraday or cfg.get("intraday")) else "1d"
        console.print(f"[cyan]Building snapshot for {args.group} "
                      f"({len(syms)} stocks, {'intraday' if interval != '1d' else 'positional'})…[/cyan]")
        text = build_snapshot(syms, interval=interval, label=args.group.upper())
        snaps = Path("snapshots"); snaps.mkdir(exist_ok=True)
        (snaps / f"snapshot_{date.today().isoformat()}.txt").write_text(text, encoding="utf-8")
        console.print("[cyan]Asking the AI analyst…[/cyan]")
        try:
            report = analyse(text, intraday=(interval != "1d"))
        except AIAnalystError as e:
            console.print(f"[red]{e}[/red]")
            console.print("[yellow]Tip: you can still run --snapshot and paste "
                          "it into Claude/ChatGPT manually.[/yellow]")
            return
        f = save_analysis(report, snaps, date.today().isoformat())
        console.print(f"\n{report}\n")
        console.print(f"[green]Saved to {f}. Review, then log paper trades "
                      f"with --buy / --sell. Om Sai Ram![/green]")
        return

    if args.snapshot:
        from saiquant.snapshot import build_snapshot
        from saiquant.universe import groups, all_symbols
        syms = all_symbols() if args.group == "all" else groups()[args.group]
        text = build_snapshot(syms, label=args.group.upper())
        out = Path("snapshots")
        out.mkdir(exist_ok=True)
        f = out / f"snapshot_{date.today().isoformat()}.txt"
        f.write_text(text, encoding="utf-8")
        console.print(text)
        console.print(f"\n[green]Saved to {f} — paste with ANALYST_PROMPT.md "
                      f"into Claude/ChatGPT. Om Sai Ram![/green]")
        return

    if args.kite_login:
        from saiquant.kite_broker import kite_login, LiveTradingBlocked
        try:
            kite_login()
        except LiveTradingBlocked as e:
            console.print(f"[red]{e}[/red]")
        except ImportError:
            console.print("[red]kiteconnect not installed. Run: "
                          "pip install kiteconnect[/red]")
        return

    if args.live_buy or args.live_sell:
        from saiquant.kite_broker import (check_gate, place_live_order,
                                          LiveTradingBlocked, CONFIRM_PHRASE)
        from saiquant.paperbook import PaperBook
        side = "BUY" if args.live_buy else "SELL"
        symbol, qty = (args.live_buy or args.live_sell)
        try:
            warnings = check_gate(cfg, PaperBook().stats()["trades"])
        except LiveTradingBlocked as e:
            console.print(f"[red]🛑 LIVE ORDER BLOCKED: {e}[/red]")
            return
        for w in warnings:
            console.print(f"[yellow]{w}[/yellow]")
        console.print(f"[bold red]REAL MONEY ORDER: {side} {qty} {symbol} "
                      f"(intraday MIS, market order)[/bold red]")
        typed = input(f'Type exactly "{CONFIRM_PHRASE}" to proceed: ')
        if typed.strip() != CONFIRM_PHRASE:
            console.print("[green]Cancelled. Saburi. 🙏[/green]")
            return
        try:
            oid = place_live_order(symbol, side, int(qty),
                                   intraday=cfg.get("intraday", True))
            console.print(f"[bold]Order placed. ID: {oid}[/bold] — verify in "
                          "your Kite app now.")
        except LiveTradingBlocked as e:
            console.print(f"[red]{e}[/red]")
        except Exception as e:
            console.print(f"[red]Order failed: {e}[/red]")
        return

    if args.dashboard:
        import threading, webbrowser
        from saiquant.dashboard import serve
        threading.Timer(1.2, lambda: webbrowser.open('http://localhost:8000')).start()
        serve()
        return

    from saiquant.paperbook import PaperBook
    book = PaperBook()

    if args.buy:
        symbol, price, qty = args.buy[0], float(args.buy[1]), int(args.buy[2])
        note = " ".join(args.buy[3:]) if len(args.buy) > 3 else ""
        book.buy(symbol, price, qty, note)
        console.print(f"[green]📝 PAPER BUY {qty} {symbol.upper()} @ ₹{price}[/green]")
        return

    if args.sell:
        symbol, price = args.sell[0], float(args.sell[1])
        pnl = book.sell(symbol, price)
        if pnl is None:
            console.print(f"[yellow]No open paper position in {symbol}[/yellow]")
        else:
            colour = "green" if pnl >= 0 else "red"
            console.print(f"[{colour}]📝 PAPER SELL {symbol.upper()} @ ₹{price} "
                          f"→ P&L ₹{pnl:,.0f}[/{colour}]")
        return

    if args.reset_campaign:
        from saiquant.autotrader import CampaignStore, reset_campaign
        store = CampaignStore()
        start = store.meta_get("start_date")
        closed = len(store.closed_trades())
        open_n = len(store.open_positions())
        console.print(f"[yellow]This will permanently delete the campaign "
                      f"started {start}: {closed} closed trades, {open_n} open "
                      f"positions, and all decision logs.[/yellow]")
        console.print(f"[dim]Storage: {store.backend()}[/dim]")
        if input('Type RESET to confirm: ').strip() != "RESET":
            console.print("[green]Cancelled — nothing was deleted.[/green]")
            return
        console.print(reset_campaign(confirm=True))
        console.print("[green]Fresh campaign will begin on the next cycle. "
                      "Om Sai Ram.[/green]")
        return

    if args.live_paper:
        from saiquant.livepaper import run_live, in_market_hours
        if not in_market_hours():
            console.print("[yellow]Outside market hours (09:15–15:30 IST).[/yellow]")
            console.print("Start it during market hours, or use "
                          "[bold]py run.py --auto[/bold] for the daily cycle.")
            return
        console.print("[bold cyan]Press Ctrl+C anytime to stop.[/bold cyan]")
        try:
            run_live(poll_minutes=args.poll, use_ai=not args.no_ai,
                     emit=lambda m: console.print(m, highlight=False))
        except KeyboardInterrupt:
            console.print("\n[yellow]Stopped by you. Open positions remain "
                          "in the campaign — run --live-paper again or "
                          "--auto this evening to manage them.[/yellow]")
        return

    if args.auto:
        from saiquant.autotrader import run_cycle
        console.print("[bold cyan]🕉  SaiQuant AI — autonomous PAPER cycle "
                      "(no real orders possible)[/bold cyan]")

        def prog(i, n, sym):
            if i % 10 == 0 or i == n:
                console.print(f"  scanning {i}/{n}…", highlight=False)

        from saiquant.autotrader import CampaignStore as _CS
        console.print(f"[dim]storage: {_CS().backend()}[/dim]")
        r = run_cycle(progress=prog, use_ai=not args.no_ai)
        console.print(f"\n[bold]Day {r['day']}[/bold] | equity "
                      f"₹{r['equity']:,.0f} | realised ₹{r['realised']:,.0f} | "
                      f"unrealised ₹{r['unrealised']:,.0f}")
        console.print(f"Open: {r['open']} | Closed: {r['closed']} | "
                      f"Nifty today: {r['index_change']}% | "
                      f"AI reviews: {r.get('ai_reviews', 0)}")
        if r["halted"]:
            console.print(f"[red]⛔ TRADING HALTED: {r['halt_reason']}[/red]")
        for e in r["events"]:
            console.print("  " + e)
        if not r["events"]:
            console.print("  [dim]No actions today — patience is a position.[/dim]")
        return

    if args.campaign or args.final_report:
        from saiquant.autotrader import CampaignStore
        from saiquant.metrics import campaign_report
        store = CampaignStore()
        start = store.meta_get("start_date")
        if not start:
            console.print("[yellow]No campaign yet. Start with: "
                          "py run.py --auto[/yellow]")
            return
        capital = float(store.meta_get("capital", 100000))
        closed = store.closed_trades()
        rep = campaign_report(capital, closed, store.equity_series(), start,
                              len(store.open_positions()))
        day_no = (datetime.now(IST).date() - date.fromisoformat(start)).days + 1

        t = Table(title="Open positions")
        for col in ("symbol", "group", "qty", "entry", "stop", "target",
                    "conf", "opened"):
            t.add_column(col)
        for p in store.open_positions():
            t.add_row(p["symbol"], p["group"], str(p["qty"]), str(p["entry"]),
                      str(p["stop"]), str(p["target"]),
                      f"{p['confidence']}/10", p["opened"])
        console.print(t)

        if closed:
            t2 = Table(title="Closed trades")
            for col in ("symbol", "qty", "entry", "exit", "P&L ₹",
                        "exit reason", "closed"):
                t2.add_column(col)
            for c_ in closed[-25:]:
                t2.add_row(c_["symbol"], str(c_["qty"]), str(c_["entry"]),
                           str(c_["exit"]), f"{c_['pnl']:,.0f}",
                           c_["exit_reason"], c_["closed"])
            console.print(t2)

        console.print(f"\n[bold]CAMPAIGN — day {day_no} of 15[/bold] "
                      f"(started {start})")
        console.print(f"  Storage          : {store.backend()}")
        console.print(f"  Capital          : ₹{capital:,.0f}")
        console.print(f"  Equity now       : ₹{rep['final_equity']:,.0f} "
                      f"({rep['return_pct']:+.2f}%)")
        console.print(f"  Closed trades    : {rep.get('trades', 0)} | "
                      f"win rate {rep.get('win_rate', 0)}%")
        console.print(f"  Expectancy/trade : ₹{rep.get('expectancy', 0):,.0f}")
        console.print(f"  Profit factor    : {rep.get('profit_factor')}")
        console.print(f"  Max drawdown     : {rep['max_drawdown_pct']}%")
        sharpe_txt = (rep['sharpe'] if rep['sharpe'] is not None
                      else 'need >= 5 days of data')
        console.print(f"  Sharpe (annlsd)  : {sharpe_txt}")
        b = rep["benchmark"]
        if b.get("available"):
            console.print(f"  Nifty buy & hold : {b['return_pct']:+.2f}% "
                          f"({b['from']} → {b['to']})")
        for n in rep["notes"]:
            console.print(f"  • {n}")

        if args.final_report:
            console.print("\n[bold]VERDICT[/bold]")
            if day_no < 15:
                console.print(f"  Campaign incomplete ({day_no}/15 days). "
                              "Judge only at completion.")
            trades = rep.get("trades", 0)
            if trades < 15:
                console.print("  ❌ NOT suitable for live trading: fewer than "
                              "15 closed trades is statistical noise.")
            elif rep.get("expectancy", 0) <= 0:
                console.print("  ❌ NOT suitable: negative expectancy.")
            elif b.get("available") and rep["return_pct"] <= b["return_pct"]:
                console.print("  ⚠️  Underperformed simple buy-and-hold — the "
                              "complexity did not earn its keep.")
            else:
                console.print("  ➡️  Continue PAPER testing for another cycle. "
                              "A single positive fortnight is not an edge.")
            console.print("  [dim]No live trading is enabled by this report. "
                          "Capital protection first.[/dim]")
        return

    if args.decisions:
        from saiquant.autotrader import CampaignStore
        rows = CampaignStore().recent_decisions(args.decisions)
        t = Table(title=f"Last {args.decisions} decisions (with reasons)")
        for col in ("time", "symbol", "action", "reason"):
            t.add_column(col, overflow="fold")
        for r_ in rows:
            t.add_row(r_[0][:16], r_[1], r_[2], r_[3])
        console.print(t)
        return

    if args.backtest:
        from saiquant.backtest import run as bt_run
        from saiquant.universe import groups, all_symbols
        syms = all_symbols() if args.group == "all" else groups()[args.group]
        console.print(f"[cyan]Backtesting {len(syms)} stocks over "
                      f"{args.years}y (stop {args.stop}%, target {args.target}%)…[/cyan]")

        def prog(i, n, sym):
            console.print(f"  [{i}/{n}] {sym}", highlight=False)

        trades, overall, per_sym = bt_run(
            syms, years=args.years, progress=prog,
            stop_pct=args.stop, target_pct=args.target)

        t = Table(title=f"Per-stock results ({args.group}, {args.years}y)")
        for col in ("symbol", "trades", "win %", "avg win %", "avg loss %",
                    "expectancy %", "total %", "max DD %"):
            t.add_column(col)
        for sym, s in per_sym.items():
            if s.get("error"):
                t.add_row(sym, "—", "—", "—", "—", "—", "—", s["error"][:20])
            elif s.get("trades"):
                t.add_row(sym, str(s["trades"]), str(s["win_rate"]),
                          str(s["avg_win"]), str(s["avg_loss"]),
                          str(s["expectancy"]), str(s["total_return_compounded"]),
                          str(s["max_drawdown"]))
            else:
                t.add_row(sym, "0", "—", "—", "—", "—", "—", "—")
        console.print(t)

        if overall.get("trades"):
            console.print(f"\n[bold]OVERALL — {overall['trades']} trades[/bold]")
            console.print(f"  Win rate         : {overall['win_rate']}%")
            console.print(f"  Avg win / loss   : +{overall['avg_win']}% / "
                          f"{overall['avg_loss']}%")
            console.print(f"  Expectancy/trade : {overall['expectancy']}%  "
                          f"(the number that matters)")
            console.print(f"  Profit factor    : {overall['profit_factor']}")
            console.print(f"  Max drawdown     : {overall['max_drawdown']}%")
            console.print(f"  Avg holding      : {overall['avg_holding_days']} days")
            verdict = ("[green]Positive expectancy — worth paper trading forward."
                       "[/green]" if overall['expectancy'] > 0 else
                       "[red]Negative expectancy — this ruleset would have lost "
                       "money. Do NOT trade it live.[/red]")
            console.print("\n" + verdict)
            console.print("[dim]Costs included ~0.25% round trip. Past results "
                          "never guarantee future ones.[/dim]")
        else:
            console.print("[yellow]No trades triggered — try more years or "
                          "a different group.[/yellow]")
        return

    if args.report:
        t1 = Table(title="Open paper positions")
        for c in ("symbol", "qty", "entry ₹", "opened", "note"):
            t1.add_column(c)
        for row in book.open_positions():
            t1.add_row(*[str(x) for x in row])
        console.print(t1)

        t2 = Table(title="Closed paper trades")
        for c in ("symbol", "qty", "entry", "exit", "P&L ₹", "opened",
                  "closed", "note"):
            t2.add_column(c)
        for row in book.closed_trades():
            t2.add_row(*[str(x) for x in row])
        console.print(t2)

        s = book.stats()
        console.print(f"\n[bold]Stats:[/bold] {s['trades']} trades | "
                      f"win rate {s['win_rate']}% | total P&L ₹{s['total_pnl']:,} | "
                      f"avg win ₹{s['avg_win']:,} | avg loss ₹{s['avg_loss']:,}")
        return

    ap.print_help()


if __name__ == "__main__":
    main()
