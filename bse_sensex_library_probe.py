import asyncio
import json
import traceback

from indiaopt import BSEClient


async def main():
    print("Testing alternative BSE SENSEX option-chain client")

    async with BSEClient() as client:
        result = await client.fetch_option_chain("999920")

        print("Fetch successful")
        print("Spot price:", result.spot_price)
        print("Expiry:", result.expiry)
        print("Number of strikes:", len(result.data))

        if not result.data:
            raise RuntimeError("No option-chain rows returned")

        print("\nSample rows:")
        for row in result.data[:5]:
            print({
                "strike": row.strike,
                "call_oi": row.call_oi,
                "put_oi": row.put_oi,
                "call_ltp": row.call_ltp,
                "put_ltp": row.put_ltp,
            })

        with open("sensex_probe_result.json", "w") as f:
            json.dump(result.to_dict(), f, indent=2, default=str)

        print("\nJSON output saved successfully")


if __name__ == "__main__":
    asyncio.run(main())
