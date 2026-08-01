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
from datetime import date
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
