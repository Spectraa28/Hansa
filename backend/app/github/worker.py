import asyncio


async def import_worker(service):
    # shortcut: one controller process owns this queue; use a leased worker before scaling to multiple processes.
    while not service.stopping.is_set():
        item = await asyncio.to_thread(service.claim_import)
        if item:
            await asyncio.to_thread(service.perform_import, item)
        else:
            await asyncio.sleep(0.5)
