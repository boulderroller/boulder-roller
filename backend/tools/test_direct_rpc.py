import asyncio
import os

from backend.app.solana_direct import mint_daily_cal


async def main():
    owner_path = os.getenv("SOLANA_OWNER_PATH")  # optional override
    sig = await mint_daily_cal(owner_path=owner_path)
    print("Explorer:", f"https://explorer.solana.com/tx/{sig}?cluster=devnet")


if __name__ == "__main__":
    asyncio.run(main())
