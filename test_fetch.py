import asyncio
import httpx
import re
import json

async def test():
    async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
        resp = await client.get(
            "https://trendshift.io/",
            headers={"User-Agent": "FleetBot/1.0"},
        )
    html = resp.text

    match = re.search(
        r'\\"initialData\\":\s*(\[.*?\])\s*\}',
        html,
        re.DOTALL,
    )

    if not match:
        print("FAILED: no match")
        return

    raw = match.group(1)
    raw = raw.replace('\\"', '"').replace('\\\\', '\\')
    repos = json.loads(raw)

    print(f"Parsed {len(repos)} repos:")
    for r in repos[:5]:
        print(f"  #{r['rank']} {r['full_name']} ⭐{r['repository_stars']} — {r.get('repository_description', '')[:60]}")

asyncio.run(test())