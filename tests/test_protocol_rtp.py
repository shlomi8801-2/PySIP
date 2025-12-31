"""
Tests for RTP protocol implementation.
"""

import pytest
from PySIP.protocol.rtp import RTPPacket, RTPHeader, DTMFEvent


class TestRTPPacket:
    """Tests for RTP packet parsing and building."""
    
    def test_parse_simple_packet(self):
        # Build a simple RTP packet
        # Header: V=2, P=0, X=0, CC=0, M=0, PT=0, seq=1234, ts=5678, ssrc=0xDEADBEEF
        header = bytes([
            0x80,  # V=2, P=0, X=0, CC=0
            0x00,  # M=0, PT=0
            0x04, 0xD2,  # seq=1234
            0x00, 0x00, 0x16, 0x2E,  # ts=5678
            0xDE, 0xAD, 0xBE, 0xEF,  # ssrc
        ])
        payload = b"\x00" * 160
        packet_data = header + payload
        
        packet = RTPPacket.parse(packet_data)
        
        assert packet.version == 2
        assert packet.marker == False
        assert packet.payload_type == 0
        assert packet.sequence == 1234
        assert packet.timestamp == 5678
        assert packet.ssrc == 0xDEADBEEF
        assert len(packet.payload) == 160
    
    def test_parse_with_marker(self):
        header = bytes([
            0x80,  # V=2
            0x80,  # M=1, PT=0
            0x00, 0x01,  # seq=1
            0x00, 0x00, 0x00, 0x00,  # ts=0
            0x00, 0x00, 0x00, 0x01,  # ssrc=1
        ])
        packet = RTPPacket.parse(header)
        
        assert packet.marker == True
    
    def test_parse_fast(self):
        header = bytes([
            0x80, 0x00,
            0x00, 0x0A,  # seq=10
            0x00, 0x00, 0x01, 0x00,  # ts=256
            0x12, 0x34, 0x56, 0x78,  # ssrc
        ])
        payload = b"\xFF" * 160
        
        packet = RTPPacket.parse_fast(header + payload)
        
        assert packet.sequence == 10
        assert packet.timestamp == 256
        assert packet.ssrc == 0x12345678
        assert len(packet.payload) == 160
    
    def test_serialize(self):
        packet = RTPPacket(
            payload_type=0,
            sequence=100,
            timestamp=8000,
            ssrc=0xABCDEF01,
            payload=b"\x00" * 80,
        )
        
        data = packet.serialize()
        
        assert len(data) == 12 + 80  # header + payload
        
        # Parse back
        parsed = RTPPacket.parse(data)
        assert parsed.sequence == 100
        assert parsed.timestamp == 8000
        assert parsed.ssrc == 0xABCDEF01
    
    def test_serialize_with_marker(self):
        packet = RTPPacket(
            payload_type=0,
            sequence=1,
            timestamp=0,
            ssrc=1,
            payload=b"",
            marker=True,
        )
        
        data = packet.serialize()
        
        # Check marker bit in second byte
        assert data[1] & 0x80 == 0x80


class TestDTMFEvent:
    """Tests for DTMF events."""
    
    def test_parse_dtmf(self):
        # DTMF '5' (event=5), end=0, volume=10, duration=320
        payload = bytes([
            0x05,  # event=5
            0x0A,  # E=0, volume=10
            0x01, 0x40,  # duration=320
        ])
        
        event = DTMFEvent.parse(payload)
        
        assert event.event == 5
        assert event.digit == "5"
        assert event.end == False
        assert event.volume == 10
        assert event.duration == 320
    
    def test_parse_dtmf_end(self):
        # DTMF '*' (event=10), end=1, volume=10, duration=800
        payload = bytes([
            0x0A,  # event=10 (*)
            0x8A,  # E=1, volume=10
            0x03, 0x20,  # duration=800
        ])
        
        event = DTMFEvent.parse(payload)
        
        assert event.digit == "*"
        assert event.end == True
    
    def test_serialize_dtmf(self):
        event = DTMFEvent(
            event=9,  # '9'
            end=True,
            volume=10,
            duration=640,
        )
        
        data = event.serialize()
        
        assert len(data) == 4
        assert data[0] == 9
        assert data[1] & 0x80  # End bit set
    
    def test_from_char(self):
        event = DTMFEvent.from_char("#", duration=160)
        
        assert event.event == 11  # '#' = 11
        assert event.digit == "#"


