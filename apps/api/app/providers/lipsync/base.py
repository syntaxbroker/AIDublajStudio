from abc import ABC, abstractmethod


class LipSyncProvider(ABC):
    capability = "LIP_SYNC"

    @abstractmethod
    async def render(self, *args, **kwargs) -> dict:
        raise NotImplementedError
