import asyncio
import httpx
import re
import json
import codecs

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

    raw = match.group(1)
    # 一次性反轉義所有層級
    raw = codecs.decode(raw, 'unicode_escape')

    try:
        repos = json.loads(raw)
        print(f"OK: {len(repos)} repos")
        for r in repos[:5]:
            print(f"  #{r['rank']} {r['full_name']} ⭐{r['repository_stars']}")
    except json.JSONDecodeError as e:
        print(f"FAILED: {e}")
        idx = e.pos
        print(f"Around error: {repr(raw[max(0,idx-30):idx+30])}")

asyncio.run(test())