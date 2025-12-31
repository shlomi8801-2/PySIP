"""
Jitter Buffer

Adaptive jitter buffer for RTP packet reordering and timing.
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from ..protocol.rtp import RTPPacket

T = TypeVar("T")


@dataclass(slots=True)
class JitterBufferStats:
    """Jitter buffer statistics."""
    
    packets_received: int = 0
    packets_played: int = 0
    packets_dropped: int = 0
    packets_lost: int = 0
    packets_late: int = 0
    packets_reordered: int = 0
    current_size: int = 0
    max_size: int = 0
    avg_jitter_ms: float = 0.0


@dataclass(slots=True, order=True)
class BufferedPacket:
    """Packet stored in jitter buffer with ordering by sequence."""
    
    sequence: int
    timestamp: int = field(compare=False)
    payload: bytes = field(compare=False)
    arrival_time: float = field(compare=False, default=0.0)
    
    @classmethod
    def from_rtp(cls, packet: "RTPPacket") -> "BufferedPacket":
        """Create from RTP packet."""
        return cls(
            sequence=packet.sequence,
            timestamp=packet.timestamp,
            payload=packet.payload,
            arrival_time=time.monotonic(),
        )


class JitterBuffer:
    """
    Adaptive jitter buffer for RTP streams.
    
    Features:
    - Reorders out-of-sequence packets
    - Handles packet loss with silence insertion
    - Adaptive depth based on measured jitter
    - Statistics tracking
    
    Example:
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        # Add received packets
        buffer.put(rtp_packet)
        
        # Get next packet for playback
        packet = buffer.get()
        if packet:
            play_audio(packet.payload)
    """
    
    __slots__ = (
        "_min_depth",
        "_max_depth",
        "_current_depth",
        "_buffer",
        "_expected_sequence",
        "_clock_rate",
        "_ptime_ms",
        "_stats",
        "_jitter_samples",
        "_last_arrival_time",
        "_last_transit",
        "_started",
        "_playing",
    )
    
    def __init__(
        self,
        min_depth: int = 2,
        max_depth: int = 10,
        clock_rate: int = 8000,
        ptime_ms: int = 20,
    ):
        """
        Initialize jitter buffer.
        
        Args:
            min_depth: Minimum buffer depth in packets
            max_depth: Maximum buffer depth in packets
            clock_rate: Audio clock rate (Hz)
            ptime_ms: Packet time in milliseconds
        """
        self._min_depth = min_depth
        self._max_depth = max_depth
        self._current_depth = min_depth
        self._clock_rate = clock_rate
        self._ptime_ms = ptime_ms
        
        # Sorted buffer (by sequence)
        self._buffer: list[BufferedPacket] = []
        
        # Expected next sequence number
        self._expected_sequence: int | None = None
        
        # Statistics
        self._stats = JitterBufferStats()
        
        # Jitter calculation
        self._jitter_samples: deque[float] = deque(maxlen=100)
        self._last_arrival_time: float | None = None
        self._last_transit: float | None = None
        
        self._started = False
        self._playing = False  # Whether we've started playing out packets
    
    @property
    def stats(self) -> JitterBufferStats:
        """Get buffer statistics."""
        return self._stats
    
    @property
    def depth(self) -> int:
        """Current buffer depth in packets."""
        return len(self._buffer)
    
    @property
    def is_ready(self) -> bool:
        """Check if buffer has enough packets to start playback."""
        # Once we've started playing, continue until empty
        if self._playing and self._buffer:
            return True
        return len(self._buffer) >= self._current_depth
    
    def put(self, packet: "RTPPacket") -> None:
        """
        Add packet to buffer.
        
        Args:
            packet: RTP packet to buffer
        """
        buffered = BufferedPacket.from_rtp(packet)
        self._stats.packets_received += 1
        
        # Initialize expected sequence from first packet
        if self._expected_sequence is None:
            self._expected_sequence = packet.sequence
            self._started = True
        
        # Calculate jitter
        self._update_jitter(buffered)
        
        # Check for late/duplicate packets
        if self._started and self._expected_sequence is not None:
            seq_diff = self._sequence_diff(packet.sequence, self._expected_sequence)
            
            # Too old - drop
            if seq_diff < -self._max_depth:
                self._stats.packets_late += 1
                self._stats.packets_dropped += 1
                return
        
        # Insert in sorted order
        self._insert_sorted(buffered)
        
        # Update stats
        self._stats.current_size = len(self._buffer)
        if self._stats.current_size > self._stats.max_size:
            self._stats.max_size = self._stats.current_size
        
        # Trim if over max depth
        while len(self._buffer) > self._max_depth:
            self._buffer.pop(0)
            self._stats.packets_dropped += 1
    
    def get(self) -> BufferedPacket | None:
        """
        Get next packet for playback.
        
        Returns:
            Next packet or None if buffer empty/not ready
        """
        # Wait until we have enough packets
        if not self.is_ready:
            return None
        
        if not self._buffer:
            return None
        
        # Get first packet
        packet = self._buffer.pop(0)
        self._playing = True  # Mark that we've started playing
        self._stats.packets_played += 1
        self._stats.current_size = len(self._buffer)
        
        # Check for gaps (missing packets)
        if self._expected_sequence is not None:
            seq_diff = self._sequence_diff(packet.sequence, self._expected_sequence)
            
            if seq_diff > 0:
                # Packets were lost
                self._stats.packets_lost += seq_diff
            elif seq_diff < 0:
                # Reordered packet
                self._stats.packets_reordered += 1
        
        # Update expected sequence
        self._expected_sequence = (packet.sequence + 1) & 0xFFFF
        
        return packet
    
    def get_or_silence(self, silence_payload: bytes) -> bytes:
        """
        Get next packet payload, or silence if unavailable.
        
        Args:
            silence_payload: Silence audio to return if no packet
            
        Returns:
            Audio payload bytes
        """
        packet = self.get()
        if packet:
            return packet.payload
        return silence_payload
    
    def clear(self) -> None:
        """Clear all buffered packets."""
        self._buffer.clear()
        self._expected_sequence = None
        self._started = False
        self._playing = False
        self._stats.current_size = 0
    
    def _insert_sorted(self, packet: BufferedPacket) -> None:
        """Insert packet in sequence order."""
        # Binary search for insertion point
        lo = 0
        hi = len(self._buffer)
        
        while lo < hi:
            mid = (lo + hi) // 2
            if self._sequence_diff(packet.sequence, self._buffer[mid].sequence) > 0:
                lo = mid + 1
            else:
                hi = mid
        
        # Check for duplicate
        if lo < len(self._buffer) and self._buffer[lo].sequence == packet.sequence:
            return  # Duplicate, don't insert
        
        self._buffer.insert(lo, packet)
    
    def _sequence_diff(self, seq1: int, seq2: int) -> int:
        """
        Calculate sequence number difference handling wraparound.
        
        Returns positive if seq1 > seq2, negative if seq1 < seq2.
        """
        diff = seq1 - seq2
        
        # Handle 16-bit wraparound
        if diff > 32768:
            diff -= 65536
        elif diff < -32768:
            diff += 65536
        
        return diff
    
    def _update_jitter(self, packet: BufferedPacket) -> None:
        """Update jitter estimate using RFC 3550 algorithm."""
        if self._last_arrival_time is None:
            self._last_arrival_time = packet.arrival_time
            self._last_transit = 0.0
            return
        
        # Calculate transit time difference
        arrival_diff = packet.arrival_time - self._last_arrival_time
        
        # Convert timestamp to seconds (assuming clock_rate)
        # This is simplified - real impl needs timestamp tracking
        
        # Inter-arrival jitter (smoothed)
        jitter_ms = abs(arrival_diff * 1000 - self._ptime_ms)
        self._jitter_samples.append(jitter_ms)
        
        # Update average jitter
        if self._jitter_samples:
            self._stats.avg_jitter_ms = sum(self._jitter_samples) / len(self._jitter_samples)
        
        # Adapt buffer depth based on jitter
        self._adapt_depth()
        
        self._last_arrival_time = packet.arrival_time
    
    def _adapt_depth(self) -> None:
        """Adapt buffer depth based on measured jitter."""
        if not self._jitter_samples:
            return
        
        avg_jitter = self._stats.avg_jitter_ms
        
        # Target depth: enough to absorb jitter
        # Each packet is ptime_ms, so depth = jitter / ptime + margin
        target_depth = int(avg_jitter / self._ptime_ms) + 1
        
        # Clamp to min/max
        target_depth = max(self._min_depth, min(self._max_depth, target_depth))
        
        # Smooth adaptation
        if target_depth > self._current_depth:
            self._current_depth = min(self._current_depth + 1, target_depth)
        elif target_depth < self._current_depth - 1:
            self._current_depth = max(self._current_depth - 1, target_depth)


class AsyncJitterBuffer(JitterBuffer):
    """
    Async-aware jitter buffer with event notifications.
    """
    
    __slots__ = ("_data_available", "_lock")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._data_available = asyncio.Event()
        self._lock = asyncio.Lock()
    
    async def put_async(self, packet: "RTPPacket") -> None:
        """Add packet asynchronously."""
        async with self._lock:
            self.put(packet)
            if self.is_ready:
                self._data_available.set()
    
    async def get_async(self, timeout: float | None = None) -> BufferedPacket | None:
        """
        Get next packet asynchronously.
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            Next packet or None on timeout
        """
        try:
            if timeout:
                await asyncio.wait_for(
                    self._data_available.wait(),
                    timeout=timeout,
                )
            else:
                await self._data_available.wait()
        except asyncio.TimeoutError:
            return None
        
        async with self._lock:
            packet = self.get()
            
            # Reset event if buffer is now empty
            if not self.is_ready:
                self._data_available.clear()
            
            return packet


