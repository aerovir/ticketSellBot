from abc import ABC, abstractmethod


class PlatformBot(ABC):
    """Abstract base class for all platform bot adapters."""

    @abstractmethod
    async def run(self):
        """Start the bot (polling or webhook)."""
        ...

    @abstractmethod
    async def stop(self):
        """Gracefully stop the bot."""
        ...
