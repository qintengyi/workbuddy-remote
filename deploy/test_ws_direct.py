import asyncio, aiohttp, json, time

async def test():
    async with aiohttp.ClientSession() as session:
        url = "http://127.0.0.1:10372/ws/agent?token=aLNV2jchftXn_eNWLJXU6YvlcNt0hs_kbAf3tAEk-Y8"
        print(f"connecting {url}")
        async with session.ws_connect(url, heartbeat=30, max_msg_size=16*1024*1024) as ws:
            print("connected")
            await ws.send_str(json.dumps({"type":"hello","data":{"agent_version":"test"}}))
            await ws.send_str(json.dumps({"type":"status","data":{"agent_online":True},"ts":int(time.time())}))
            print("sent hello+status")
            start = time.time()
            async for msg in ws:
                elapsed = time.time() - start
                if msg.type == aiohttp.WSMsgType.TEXT:
                    print(f"[{elapsed:.1f}s] recv: {msg.data[:100]}")
                elif msg.type == aiohttp.WSMsgType.CLOSED:
                    print(f"[{elapsed:.1f}s] CLOSED")
                    break
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    print(f"[{elapsed:.1f}s] ERROR: {ws.exception()}")
                    break
                if elapsed > 40:
                    print(f"[{elapsed:.1f}s] stable for 40s, exiting")
                    break

asyncio.run(test())
