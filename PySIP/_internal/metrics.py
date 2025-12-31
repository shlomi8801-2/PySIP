"""
Performance Metrics

Collects and reports performance metrics for monitoring.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CallMetrics:
    """Metrics for a single call."""
    
    call_id: str
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    
    # RTP metrics
    rtp_packets_sent: int = 0
    rtp_packets_received: int = 0
    rtp_bytes_sent: int = 0
    rtp_bytes_received: int = 0
    rtp_packets_lost: int = 0
    
    # Quality metrics
    jitter_ms: float = 0.0
    round_trip_time_ms: float = 0.0
    mos_score: float = 0.0
    
    # Event counts
    dtmf_received: int = 0
    hold_count: int = 0
    
    @property
    def duration_seconds(self) -> float:
        """Call duration in seconds."""
        end = self.end_time or time.time()
        return end - self.start_time
    
    @property
    def packet_loss_rate(self) -> float:
        """Packet loss percentage."""
        total = self.rtp_packets_received + self.rtp_packets_lost
        if total == 0:
            return 0.0
        return (self.rtp_packets_lost / total) * 100


@dataclass(slots=True)
class SystemMetrics:
    """System-wide metrics."""
    
    timestamp: float = field(default_factory=time.time)
    
    # Call counts
    active_calls: int = 0
    total_calls: int = 0
    failed_calls: int = 0
    
    # Event loop metrics
    event_loop_lag_ms: float = 0.0
    pending_tasks: int = 0
    
    # Memory (if psutil available)
    memory_mb: float = 0.0
    
    # Network
    packets_per_second: float = 0.0
    bytes_per_second: float = 0.0


class MetricsCollector:
    """
    Collects and aggregates performance metrics.
    
    Example:
        collector = MetricsCollector()
        collector.start()
        
        # Record call metrics
        collector.record_call_start(call_id)
        collector.record_rtp_packet_sent(call_id, 160)
        collector.record_call_end(call_id)
        
        # Get aggregated metrics
        stats = collector.get_stats()
        print(f"Active calls: {stats['active_calls']}")
    """
    
    __slots__ = (
        "_call_metrics",
        "_system_metrics",
        "_running",
        "_collection_task",
        "_collection_interval",
        "_lag_samples",
        "_packet_counts",
    )
    
    def __init__(self, collection_interval: float = 1.0):
        self._call_metrics: dict[str, CallMetrics] = {}
        self._system_metrics: deque[SystemMetrics] = deque(maxlen=60)  # 1 minute history
        self._running = False
        self._collection_task: asyncio.Task | None = None
        self._collection_interval = collection_interval
        self._lag_samples: deque[float] = deque(maxlen=100)
        self._packet_counts: deque[tuple[float, int, int]] = deque(maxlen=60)
    
    def start(self) -> None:
        """Start metrics collection."""
        if self._running:
            return
        
        self._running = True
        self._collection_task = asyncio.create_task(self._collection_loop())
        logger.info("MetricsCollector started")
    
    def stop(self) -> None:
        """Stop metrics collection."""
        self._running = False
        if self._collection_task:
            self._collection_task.cancel()
            self._collection_task = None
    
    async def _collection_loop(self) -> None:
        """Periodic metrics collection."""
        last_time = time.time()
        last_packets = 0
        last_bytes = 0
        
        try:
            while self._running:
                # Measure event loop lag
                expected_time = asyncio.get_running_loop().time()
                await asyncio.sleep(self._collection_interval)
                actual_time = asyncio.get_running_loop().time()
                lag_ms = (actual_time - expected_time - self._collection_interval) * 1000
                self._lag_samples.append(max(0, lag_ms))
                
                # Calculate packet rate
                current_time = time.time()
                current_packets = sum(m.rtp_packets_sent + m.rtp_packets_received for m in self._call_metrics.values())
                current_bytes = sum(m.rtp_bytes_sent + m.rtp_bytes_received for m in self._call_metrics.values())
                
                time_delta = current_time - last_time
                if time_delta > 0:
                    pps = (current_packets - last_packets) / time_delta
                    bps = (current_bytes - last_bytes) / time_delta
                else:
                    pps = 0
                    bps = 0
                
                last_time = current_time
                last_packets = current_packets
                last_bytes = current_bytes
                
                # Collect system metrics
                metrics = SystemMetrics(
                    timestamp=current_time,
                    active_calls=len([m for m in self._call_metrics.values() if m.end_time is None]),
                    total_calls=len(self._call_metrics),
                    event_loop_lag_ms=sum(self._lag_samples) / len(self._lag_samples) if self._lag_samples else 0,
                    pending_tasks=len(asyncio.all_tasks()),
                    packets_per_second=pps,
                    bytes_per_second=bps,
                )
                
                # Try to get memory usage
                try:
                    import psutil
                    process = psutil.Process()
                    metrics.memory_mb = process.memory_info().rss / 1024 / 1024
                except ImportError:
                    pass
                
                self._system_metrics.append(metrics)
        
        except asyncio.CancelledError:
            pass
    
    # === Call Metrics ===
    
    def record_call_start(self, call_id: str) -> None:
        """Record call start."""
        self._call_metrics[call_id] = CallMetrics(call_id=call_id)
    
    def record_call_end(self, call_id: str) -> None:
        """Record call end."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].end_time = time.time()
    
    def record_rtp_packet_sent(self, call_id: str, size: int) -> None:
        """Record RTP packet sent."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].rtp_packets_sent += 1
            self._call_metrics[call_id].rtp_bytes_sent += size
    
    def record_rtp_packet_received(self, call_id: str, size: int) -> None:
        """Record RTP packet received."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].rtp_packets_received += 1
            self._call_metrics[call_id].rtp_bytes_received += size
    
    def record_packet_loss(self, call_id: str, count: int = 1) -> None:
        """Record packet loss."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].rtp_packets_lost += count
    
    def record_jitter(self, call_id: str, jitter_ms: float) -> None:
        """Record jitter measurement."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].jitter_ms = jitter_ms
    
    def record_dtmf(self, call_id: str) -> None:
        """Record DTMF received."""
        if call_id in self._call_metrics:
            self._call_metrics[call_id].dtmf_received += 1
    
    # === Query Methods ===
    
    def get_call_metrics(self, call_id: str) -> CallMetrics | None:
        """Get metrics for specific call."""
        return self._call_metrics.get(call_id)
    
    def get_active_calls(self) -> list[CallMetrics]:
        """Get metrics for all active calls."""
        return [m for m in self._call_metrics.values() if m.end_time is None]
    
    def get_latest_system_metrics(self) -> SystemMetrics | None:
        """Get most recent system metrics."""
        if self._system_metrics:
            return self._system_metrics[-1]
        return None
    
    def get_stats(self) -> dict:
        """
        Get aggregated statistics.
        
        Returns:
            Dictionary with summary statistics
        """
        active_calls = [m for m in self._call_metrics.values() if m.end_time is None]
        completed_calls = [m for m in self._call_metrics.values() if m.end_time is not None]
        
        total_packets_sent = sum(m.rtp_packets_sent for m in self._call_metrics.values())
        total_packets_received = sum(m.rtp_packets_received for m in self._call_metrics.values())
        total_packets_lost = sum(m.rtp_packets_lost for m in self._call_metrics.values())
        
        latest = self.get_latest_system_metrics()
        
        return {
            "active_calls": len(active_calls),
            "completed_calls": len(completed_calls),
            "total_calls": len(self._call_metrics),
            "total_packets_sent": total_packets_sent,
            "total_packets_received": total_packets_received,
            "total_packets_lost": total_packets_lost,
            "packet_loss_rate": (total_packets_lost / max(1, total_packets_received + total_packets_lost)) * 100,
            "event_loop_lag_ms": latest.event_loop_lag_ms if latest else 0,
            "packets_per_second": latest.packets_per_second if latest else 0,
            "memory_mb": latest.memory_mb if latest else 0,
        }
    
    def cleanup_old_calls(self, max_age_seconds: float = 3600) -> int:
        """
        Remove metrics for old completed calls.
        
        Args:
            max_age_seconds: Maximum age for completed call metrics
            
        Returns:
            Number of calls removed
        """
        cutoff = time.time() - max_age_seconds
        to_remove = [
            call_id for call_id, m in self._call_metrics.items()
            if m.end_time is not None and m.end_time < cutoff
        ]
        
        for call_id in to_remove:
            del self._call_metrics[call_id]
        
        return len(to_remove)


# Global metrics collector
_metrics_collector: MetricsCollector | None = None


def get_metrics_collector() -> MetricsCollector:
    """Get global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


