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
