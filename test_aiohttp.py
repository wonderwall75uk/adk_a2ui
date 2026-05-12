import aiohttp
import asyncio

async def test():
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get("https://generativelanguage.googleapis.com", timeout=5) as r:
                print(f"Status: {r.status}")
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(test())
