"""CLI entry point for ATLAS.

Supports:
  atlas live              — one EOD cycle for today
  atlas backtest --start … --end …
  atlas status            — show agent weights
  atlas --days N          — simple N-day mock backtest
"""

import argparse
import json
import sys
from datetime import datetime

from .config import Config, AGENT_DEFINITIONS, ALL_AGENTS
from .utils.llm import make_llm_client
from .utils.logging import get_logger


def _console():
    from rich.console import Console
    return Console()


# ---------------------------------------------------------------------------
# Subcommands
# ---------------------------------------------------------------------------

def cmd_live(config: Config) -> None:
    console = _console()
    llm = make_llm_client(config)
    today = datetime.now().strftime("%Y-%m-%d")
    console.print(f"\n[bold green]ATLAS Live Mode[/bold green] — {today}\n")

    from .agents.backtest_loop import load_portfolio, mark_to_market, execute_actions, save_portfolio
    from .agents.market_data import get_market_snapshot
    from .agents.eod_cycle import run_full_cycle
    from .agents.scorecard import update_forward_returns, update_darwinian_weights, load_darwinian_weights
    from .agents.autoresearch import maybe_run_autoresearch

    portfolio = load_portfolio(config)
    console.print(f"Portfolio value: ${portfolio['total_value']:,.0f}")

    update_forward_returns(today, config)
    market_data = get_market_snapshot(today, config)
    weights = load_darwinian_weights(config)
    cio = run_full_cycle(market_data, portfolio, config, llm, weights)

    console.print("\n[bold]CIO Decisions:[/bold]")
    actions = cio.get("actions") or cio.get("portfolio_actions", [])
    for a in actions:
        console.print(f"  {a.get('action', '?')} {a.get('ticker', '?')} x{a.get('shares', 0)}")

    portfolio = execute_actions(portfolio, actions, today, config)
    portfolio = mark_to_market(portfolio, today, config)
    save_portfolio(portfolio, config)

    update_darwinian_weights(today, config)
    day_num = (datetime.now() - datetime(2024, 9, 1)).days
    maybe_run_autoresearch(today, day_num, config, llm)


def cmd_backtest(start: str, end: str, resume: bool, config: Config) -> None:
    console = _console()
    llm = make_llm_client(config)
    console.print(f"\n[bold green]ATLAS Backtest[/bold green]")
    console.print(f"Period: {start} -> {end} | Resume: {resume}\n")

    from .agents.backtest_loop import run_backtest
    result = run_backtest(start, end, config, llm, resume=resume)

    console.print(f"\n[bold]Results:[/bold]")
    console.print(f"  Trading days: {result['trading_days']}")
    console.print(f"  Starting: ${result['starting_value']:,.0f}")
    console.print(f"  Ending:   ${result['ending_value']:,.0f}")
    console.print(f"  Return:   {result['total_return_pct']:.1f}%")


def cmd_status(config: Config) -> None:
    from rich.table import Table
    console = _console()

    from .agents.scorecard import load_darwinian_weights, get_all_agent_sharpes
    weights = load_darwinian_weights(config)
    sharpes = get_all_agent_sharpes(config, lookback_days=60)

    table = Table(title="ATLAS Agent Status")
    table.add_column("Agent", style="cyan")
    table.add_column("Layer", justify="center")
    table.add_column("Weight", justify="right")
    table.add_column("Sharpe (60d)", justify="right")

    layer_names = {1: "Macro", 2: "Sector", 3: "Super", 4: "Decision"}
    for agent, info in AGENT_DEFINITIONS.items():
        w = weights.get(agent, 1.0)
        s = sharpes.get(agent)
        s_str = f"{s:.3f}" if s is not None else "N/A"
        style = "green" if w >= 2.0 else "red" if w <= 0.4 else "white"
        table.add_row(agent, layer_names[info["layer"]], f"[{style}]{w:.2f}[/{style}]", s_str)

    console.print(table)

    ar_log = config.data_dir / "track_record" / "autoresearch_log.json"
    if ar_log.exists():
        with open(ar_log) as f:
            log = json.load(f)
        kept = sum(1 for e in log if e.get("kept"))
        console.print(
            f"\n[bold]Autoresearch:[/bold] {len(log)} attempts, {kept} kept "
            f"({100 * kept // max(len(log), 1)}% success)"
        )


def cmd_simple(days: int, config: Config) -> None:
    """Simple N-day backtest (josjo80 style)."""
    llm = make_llm_client(config)
    logger = get_logger("atlas", config.log_dir)
    logger.info("Starting ATLAS simple run for %s day(s)", days)
    from .agents.backtest_loop import run_simple_backtest
    run_simple_backtest(days, config, llm)
    logger.info("Finished ATLAS run")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="ATLAS — Self-Improving AI Trading Agents")
    parser.add_argument("--days", type=int, default=0, help="Quick N-day mock backtest")

    sub = parser.add_subparsers(dest="command")
    sub.add_parser("live", help="Run one EOD cycle for today")

    bt = sub.add_parser("backtest", help="Run historical backtest")
    bt.add_argument("--start", required=True, help="Start date YYYY-MM-DD")
    bt.add_argument("--end", required=True, help="End date YYYY-MM-DD")
    bt.add_argument("--resume", action="store_true")

    sub.add_parser("status", help="Show agent weights and performance")

    args = parser.parse_args()
    config = Config.from_env()

    if args.days > 0:
        cmd_simple(args.days, config)
    elif args.command == "live":
        cmd_live(config)
    elif args.command == "backtest":
        cmd_backtest(args.start, args.end, args.resume, config)
    elif args.command == "status":
        cmd_status(config)
    else:
        parser.print_help()
