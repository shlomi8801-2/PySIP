"""
Tests for jitter buffer.
"""

import pytest
from PySIP.media.jitter import JitterBuffer, BufferedPacket


class MockRTPPacket:
    """Mock RTP packet for testing."""
    
    def __init__(self, sequence: int, timestamp: int = 0, payload: bytes = b""):
        self.sequence = sequence
        self.timestamp = timestamp
        self.payload = payload or b"\x00" * 160


class TestJitterBuffer:
    """Tests for jitter buffer."""
    
    def test_basic_buffering(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        # Add packets
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=2))
        
        assert buffer.depth == 2
        assert buffer.is_ready
    
    def test_ordering(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        # Add out of order
        buffer.put(MockRTPPacket(sequence=3))
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=2))
        
        # Should come out in order
        p1 = buffer.get()
        p2 = buffer.get()
        p3 = buffer.get()
        
        assert p1.sequence == 1
        assert p2.sequence == 2
        assert p3.sequence == 3
    
    def test_min_depth_wait(self):
        buffer = JitterBuffer(min_depth=3, max_depth=10)
        
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=2))
        
        # Not ready yet
        assert not buffer.is_ready
        assert buffer.get() is None
        
        buffer.put(MockRTPPacket(sequence=3))
        
        # Now ready
        assert buffer.is_ready
        assert buffer.get() is not None
    
    def test_max_depth_trim(self):
        buffer = JitterBuffer(min_depth=2, max_depth=5)
        
        # Add more than max
        for i in range(10):
            buffer.put(MockRTPPacket(sequence=i))
        
        # Should be trimmed to max
        assert buffer.depth <= 5
    
    def test_duplicate_handling(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=1))  # Duplicate
        buffer.put(MockRTPPacket(sequence=2))
        
        # Should only have 2 packets
        assert buffer.depth == 2
    
    def test_sequence_wraparound(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        # Near wraparound point
        buffer.put(MockRTPPacket(sequence=65534))
        buffer.put(MockRTPPacket(sequence=65535))
        buffer.put(MockRTPPacket(sequence=0))  # Wrapped
        buffer.put(MockRTPPacket(sequence=1))
        
        # Should handle correctly
        p1 = buffer.get()
        p2 = buffer.get()
        
        assert p1.sequence == 65534
        assert p2.sequence == 65535
    
    def test_clear(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=2))
        buffer.clear()
        
        assert buffer.depth == 0
        assert not buffer.is_ready
    
    def test_statistics(self):
        buffer = JitterBuffer(min_depth=2, max_depth=10)
        
        buffer.put(MockRTPPacket(sequence=1))
        buffer.put(MockRTPPacket(sequence=2))
        buffer.get()
        
        stats = buffer.stats
        assert stats.packets_received == 2
        assert stats.packets_played == 1


