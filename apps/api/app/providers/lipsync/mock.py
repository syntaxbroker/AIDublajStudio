from app.providers.lipsync.base import LipSyncProvider


class MockLipSyncProvider(LipSyncProvider):
    async def render(self, *args, **kwargs) -> dict:
        return {"status": "not_implemented"}
