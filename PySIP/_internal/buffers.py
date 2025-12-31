"""
Buffer Pool

Pre-allocated buffer pool for zero-allocation packet handling.
"""

from __future__ import annotations

import asyncio
from collections import deque
from typing import TYPE_CHECKING


class BufferPool:
    """
    Pre-allocated buffer pool for RTP packets.
    
    Reduces memory allocation overhead for high-frequency
    packet processing.
    
    Example:
        pool = BufferPool(buffer_size=1500, pool_size=100)
        
        # Acquire buffer
        buf = await pool.acquire()
        
        # Use buffer...
        buf[:12] = rtp_header
        
        # Release back to pool
        await pool.release(buf)
    """
    
    __slots__ = ("_buffer_size", "_pool", "_lock", "_created", "_max_size")
    
    def __init__(
        self,
        buffer_size: int = 1500,
        pool_size: int = 100,
    ):
        """
        Initialize buffer pool.
        
        Args:
            buffer_size: Size of each buffer in bytes
            pool_size: Number of pre-allocated buffers
        """
        self._buffer_size = buffer_size
        self._max_size = pool_size
        self._pool: deque[bytearray] = deque(
            bytearray(buffer_size) for _ in range(pool_size)
        )
        self._lock = asyncio.Lock()
        self._created = pool_size
    
    @property
    def available(self) -> int:
        """Number of available buffers."""
        return len(self._pool)
    
    @property
    def buffer_size(self) -> int:
        """Size of each buffer."""
        return self._buffer_size
    
    async def acquire(self) -> bytearray:
        """
        Acquire buffer from pool.
        
        Returns:
            Buffer (may be newly allocated if pool empty)
        """
        async with self._lock:
            if self._pool:
                return self._pool.popleft()
            
            # Pool exhausted - create new buffer
            self._created += 1
            return bytearray(self._buffer_size)
    
    async def release(self, buf: bytearray) -> None:
        """
        Release buffer back to pool.
        
        Args:
            buf: Buffer to release
        """
        async with self._lock:
            # Only keep up to max_size buffers
            if len(self._pool) < self._max_size:
                # Clear buffer before returning
                for i in range(len(buf)):
                    buf[i] = 0
                self._pool.append(buf)
    
    def acquire_sync(self) -> bytearray:
        """Synchronous acquire (no lock - use with caution)."""
        if self._pool:
            return self._pool.popleft()
        self._created += 1
        return bytearray(self._buffer_size)
    
    def release_sync(self, buf: bytearray) -> None:
        """Synchronous release (no lock - use with caution)."""
        if len(self._pool) < self._max_size:
            self._pool.append(buf)


class BytesPool:
    """
    Pool for immutable bytes objects.
    
    Uses a simple cache with LRU-like behavior for common
    byte patterns (e.g., silence frames).
    """
    
    __slots__ = ("_cache", "_max_size")
    
    def __init__(self, max_size: int = 100):
        self._cache: dict[int, bytes] = {}
        self._max_size = max_size
    
    def get_zeros(self, size: int) -> bytes:
        """
        Get zero-filled bytes of given size.
        
        Args:
            size: Number of bytes
            
        Returns:
            Zero-filled bytes (may be cached)
        """
        if size in self._cache:
            return self._cache[size]
        
        data = b"\x00" * size
        
        # Cache if under limit
        if len(self._cache) < self._max_size:
            self._cache[size] = data
        
        return data
    
    def get_silence_ulaw(self, samples: int) -> bytes:
        """
        Get μ-law silence frame.
        
        Args:
            samples: Number of samples
            
        Returns:
            μ-law encoded silence
        """
        # μ-law silence is 0xFF
        key = -samples  # Use negative to distinguish from zeros
        if key in self._cache:
            return self._cache[key]
        
        data = b"\xff" * samples
        
        if len(self._cache) < self._max_size:
            self._cache[key] = data
        
        return data
    
    def get_silence_alaw(self, samples: int) -> bytes:
        """
        Get A-law silence frame.
        
        Args:
            samples: Number of samples
            
        Returns:
            A-law encoded silence
        """
        # A-law silence is 0xD5
        key = -samples - 100000  # Different key space
        if key in self._cache:
            return self._cache[key]
        
        data = b"\xd5" * samples
        
        if len(self._cache) < self._max_size:
            self._cache[key] = data
        
        return data


# Global instances
_buffer_pool: BufferPool | None = None
_bytes_pool: BytesPool | None = None


def get_buffer_pool() -> BufferPool:
    """Get global buffer pool instance."""
    global _buffer_pool
    if _buffer_pool is None:
        _buffer_pool = BufferPool()
    return _buffer_pool


def get_bytes_pool() -> BytesPool:
    """Get global bytes pool instance."""
    global _bytes_pool
    if _bytes_pool is None:
        _bytes_pool = BytesPool()
    return _bytes_pool


