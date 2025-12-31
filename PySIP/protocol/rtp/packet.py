"""
RTP Packet

RFC 3550 compliant RTP packet handling with high-performance parsing.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING


@dataclass(slots=True)
class RTPHeader:
    """
    RTP header fields.
    
    Fixed 12-byte header (may be followed by CSRC list and extension).
    
     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |V=2|P|X|  CC   |M|     PT      |       sequence number         |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |                           timestamp                           |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |           synchronization source (SSRC) identifier            |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    
    version: int = 2
    padding: bool = False
    extension: bool = False
    csrc_count: int = 0
    marker: bool = False
    payload_type: int = 0
    sequence: int = 0
    timestamp: int = 0
    ssrc: int = 0
    csrc_list: list[int] | None = None
    
    @property
    def header_length(self) -> int:
        """Total header length in bytes."""
        return 12 + (4 * self.csrc_count)


class RTPPacket:
    """
    RTP packet with zero-copy parsing.
    
    Uses __slots__ for memory efficiency.
    
    Example:
        # Parse received packet
        packet = RTPPacket.parse(data)
        print(f"PT={packet.payload_type}, seq={packet.sequence}")
        audio = packet.payload
        
        # Build packet
        packet = RTPPacket(
            payload_type=0,
            sequence=1234,
            timestamp=0,
            ssrc=0xDEADBEEF,
            payload=audio_data,
        )
        data = packet.serialize()
    """
    
    __slots__ = (
        "version",
        "padding",
        "extension",
        "csrc_count",
        "marker",
        "payload_type",
        "sequence",
        "timestamp",
        "ssrc",
        "csrc_list",
        "payload",
        "_raw",
    )
    
    def __init__(
        self,
        payload_type: int = 0,
        sequence: int = 0,
        timestamp: int = 0,
        ssrc: int = 0,
        payload: bytes = b"",
        marker: bool = False,
        version: int = 2,
        padding: bool = False,
        extension: bool = False,
        csrc_list: list[int] | None = None,
    ):
        self.version = version
        self.padding = padding
        self.extension = extension
        self.marker = marker
        self.payload_type = payload_type
        self.sequence = sequence
        self.timestamp = timestamp
        self.ssrc = ssrc
        self.csrc_list = csrc_list or []
        self.csrc_count = len(self.csrc_list)
        self.payload = payload
        self._raw: bytes | None = None
    
    @classmethod
    def parse(cls, data: bytes) -> "RTPPacket":
        """
        Parse RTP packet from bytes.
        
        Fast path: minimal allocations, direct struct unpacking.
        
        Args:
            data: Raw RTP packet bytes (minimum 12 bytes)
            
        Returns:
            Parsed RTPPacket
            
        Raises:
            ValueError: If packet is too short or invalid
        """
        if len(data) < 12:
            raise ValueError(f"RTP packet too short: {len(data)} bytes")
        
        # Unpack fixed header (12 bytes)
        byte0, byte1, sequence, timestamp, ssrc = struct.unpack_from(
            "!BBHII", data, 0
        )
        
        # Parse first byte
        version = (byte0 >> 6) & 0x03
        padding = bool((byte0 >> 5) & 0x01)
        extension = bool((byte0 >> 4) & 0x01)
        csrc_count = byte0 & 0x0F
        
        # Parse second byte
        marker = bool((byte1 >> 7) & 0x01)
        payload_type = byte1 & 0x7F
        
        # Validate version
        if version != 2:
            raise ValueError(f"Invalid RTP version: {version}")
        
        # Calculate header length
        header_len = 12 + (4 * csrc_count)
        
        if len(data) < header_len:
            raise ValueError("RTP packet too short for CSRC list")
        
        # Parse CSRC list if present
        csrc_list = []
        if csrc_count > 0:
            for i in range(csrc_count):
                csrc = struct.unpack_from("!I", data, 12 + (i * 4))[0]
                csrc_list.append(csrc)
        
        # Handle extension header
        if extension:
            if len(data) < header_len + 4:
                raise ValueError("RTP packet too short for extension header")
            
            ext_len = struct.unpack_from("!H", data, header_len + 2)[0]
            header_len += 4 + (ext_len * 4)
        
        # Handle padding
        payload_end = len(data)
        if padding and len(data) > header_len:
            padding_len = data[-1]
            payload_end -= padding_len
        
        # Extract payload
        payload = data[header_len:payload_end]
        
        packet = cls.__new__(cls)
        packet.version = version
        packet.padding = padding
        packet.extension = extension
        packet.csrc_count = csrc_count
        packet.marker = marker
        packet.payload_type = payload_type
        packet.sequence = sequence
        packet.timestamp = timestamp
        packet.ssrc = ssrc
        packet.csrc_list = csrc_list
        packet.payload = payload
        packet._raw = data
        
        return packet
    
    @classmethod
    def parse_fast(cls, data: bytes) -> "RTPPacket":
        """
        Ultra-fast parsing for hot path.
        
        Skips validation and CSRC parsing for maximum speed.
        Use when you know the packet is valid RTP.
        """
        byte0, byte1, sequence, timestamp, ssrc = struct.unpack_from(
            "!BBHII", data, 0
        )
        
        packet = cls.__new__(cls)
        packet.version = 2
        packet.padding = False
        packet.extension = False
        packet.csrc_count = 0
        packet.marker = bool((byte1 >> 7) & 0x01)
        packet.payload_type = byte1 & 0x7F
        packet.sequence = sequence
        packet.timestamp = timestamp
        packet.ssrc = ssrc
        packet.csrc_list = []
        packet.payload = data[12:]  # Assume no CSRC, no extension
        packet._raw = data
        
        return packet
    
    def serialize(self) -> bytes:
        """
        Serialize packet to bytes.
        
        Returns:
            Wire-format bytes
        """
        # Build first byte
        byte0 = (
            ((self.version & 0x03) << 6) |
            ((1 if self.padding else 0) << 5) |
            ((1 if self.extension else 0) << 4) |
            (self.csrc_count & 0x0F)
        )
        
        # Build second byte
        byte1 = ((1 if self.marker else 0) << 7) | (self.payload_type & 0x7F)
        
        # Pack header
        header = struct.pack(
            "!BBHII",
            byte0,
            byte1,
            self.sequence & 0xFFFF,
            self.timestamp & 0xFFFFFFFF,
            self.ssrc & 0xFFFFFFFF,
        )
        
        # Add CSRC list
        if self.csrc_list:
            for csrc in self.csrc_list:
                header += struct.pack("!I", csrc)
        
        return header + self.payload
    
    def __repr__(self) -> str:
        return (
            f"RTPPacket(PT={self.payload_type}, seq={self.sequence}, "
            f"ts={self.timestamp}, ssrc={self.ssrc:08x}, "
            f"payload={len(self.payload)}B, marker={self.marker})"
        )


# Pre-allocate header struct for repeated use
_RTP_HEADER_STRUCT = struct.Struct("!BBHII")


def parse_rtp_header(data: bytes) -> tuple[int, int, int, int, int, bool]:
    """
    Parse only RTP header fields.
    
    Returns:
        Tuple of (payload_type, sequence, timestamp, ssrc, header_len, marker)
    """
    if len(data) < 12:
        raise ValueError("Data too short for RTP header")
    
    byte0, byte1, sequence, timestamp, ssrc = _RTP_HEADER_STRUCT.unpack_from(data, 0)
    
    csrc_count = byte0 & 0x0F
    marker = bool((byte1 >> 7) & 0x01)
    payload_type = byte1 & 0x7F
    header_len = 12 + (4 * csrc_count)
    
    return payload_type, sequence, timestamp, ssrc, header_len, marker


def build_rtp_packet(
    payload_type: int,
    sequence: int,
    timestamp: int,
    ssrc: int,
    payload: bytes,
    marker: bool = False,
) -> bytes:
    """
    Build RTP packet bytes directly.
    
    Faster than creating RTPPacket object when you just need bytes.
    """
    byte0 = 0x80  # Version 2, no padding/extension/CSRC
    byte1 = (0x80 if marker else 0x00) | (payload_type & 0x7F)
    
    header = _RTP_HEADER_STRUCT.pack(
        byte0,
        byte1,
        sequence & 0xFFFF,
        timestamp & 0xFFFFFFFF,
        ssrc & 0xFFFFFFFF,
    )
    
    return header + payload


