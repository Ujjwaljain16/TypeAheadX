from abc import ABC, abstractmethod
from typing import Optional, Any

class CacheInterface(ABC):
    """
    Abstract interface for cache operations.
    Ensures business logic is decoupled from the storage engine.
    """
    
    @abstractmethod
    def get(self, key: str) -> Optional[Any]:
        pass

    @abstractmethod
    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        pass

    @abstractmethod
    def get_ttl(self, key: str) -> int:
        pass

    # Raw (pre-serialised string) access: lets the hot path serve cached JSON without a decode/encode
    # round trip. Providers that serialise values themselves (Redis) override these; the defaults suit
    # providers that store Python objects as-is (in-memory).
    def get_raw(self, key: str) -> Optional[str]:
        value = self.get(key)
        return value if isinstance(value, str) else None

    def set_raw(self, key: str, text: str, ttl_seconds: int) -> None:
        self.set(key, text, ttl_seconds)

    def delete_many(self, keys) -> None:
        for key in keys:
            self.delete(key)
