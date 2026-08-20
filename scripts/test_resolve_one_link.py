import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main
from playwright.async_api import async_playwright


def default_shortlink():
    for shortlink in main.MASTER_RESOLVED_CACHE:
        if main.normalize_shortlink(shortlink) != "N/A":
            return shortlink
    raise SystemExit("No shortlink found in master cache to test.")


async def resolve(shortlink, use_cache):
    if not use_cache:
        main.MASTER_RESOLVED_CACHE = {}
    async with async_playwright() as playwright:
        return await main.resolve_one_shortlink(playwright, shortlink)


def parse_args():
    parser = argparse.ArgumentParser(description="Resolve one shortlink and print the Telegram bot URL.")
    parser.add_argument("shortlink", nargs="?", help="Shortlink to resolve; defaults to the first cached shortlink.")
    parser.add_argument("--no-cache", action="store_true", help="Force a live Playwright resolution instead of using master_resolved_cache.json.")
    return parser.parse_args()


def main_cli():
    main.load_resolved_cache()
    args = parse_args()
    shortlink = args.shortlink or default_shortlink()
    bot_link = asyncio.run(resolve(shortlink, use_cache=not args.no_cache))
    print(f"SHORTLINK={shortlink}")
    print(f"BOT_LINK={bot_link}")
    if not bot_link or bot_link == "N/A":
        raise SystemExit(1)


if __name__ == "__main__":
    main_cli()
