"""
RFC 2833 DTMF Events

DTMF signaling via RTP telephone-event payload.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING


class DTMFType(IntEnum):
    """DTMF event codes per RFC 2833."""
    
    DIGIT_0 = 0
    DIGIT_1 = 1
    DIGIT_2 = 2
    DIGIT_3 = 3
    DIGIT_4 = 4
    DIGIT_5 = 5
    DIGIT_6 = 6
    DIGIT_7 = 7
    DIGIT_8 = 8
    DIGIT_9 = 9
    STAR = 10    # *
    POUND = 11   # #
    A = 12
    B = 13
    C = 14
    D = 15
    
    # Flash events
    FLASH = 16


# Map characters to DTMF codes
CHAR_TO_DTMF = {
    "0": DTMFType.DIGIT_0,
    "1": DTMFType.DIGIT_1,
    "2": DTMFType.DIGIT_2,
    "3": DTMFType.DIGIT_3,
    "4": DTMFType.DIGIT_4,
    "5": DTMFType.DIGIT_5,
    "6": DTMFType.DIGIT_6,
    "7": DTMFType.DIGIT_7,
    "8": DTMFType.DIGIT_8,
    "9": DTMFType.DIGIT_9,
    "*": DTMFType.STAR,
    "#": DTMFType.POUND,
    "A": DTMFType.A,
    "a": DTMFType.A,
    "B": DTMFType.B,
    "b": DTMFType.B,
    "C": DTMFType.C,
    "c": DTMFType.C,
    "D": DTMFType.D,
    "d": DTMFType.D,
}

# Map DTMF codes to characters
DTMF_TO_CHAR = {
    DTMFType.DIGIT_0: "0",
    DTMFType.DIGIT_1: "1",
    DTMFType.DIGIT_2: "2",
    DTMFType.DIGIT_3: "3",
    DTMFType.DIGIT_4: "4",
    DTMFType.DIGIT_5: "5",
    DTMFType.DIGIT_6: "6",
    DTMFType.DIGIT_7: "7",
    DTMFType.DIGIT_8: "8",
    DTMFType.DIGIT_9: "9",
    DTMFType.STAR: "*",
    DTMFType.POUND: "#",
    DTMFType.A: "A",
    DTMFType.B: "B",
    DTMFType.C: "C",
    DTMFType.D: "D",
}


@dataclass(slots=True)
class DTMFEvent:
    """
    RFC 2833 DTMF event.
    
    Event payload format (4 bytes):
     0                   1                   2                   3
     0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1 2 3 4 5 6 7 8 9 0 1
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    |     event     |E|R| volume    |          duration             |
    +-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+-+
    """
    
    event: int  # DTMF digit code (0-15 for digits, 16 for flash)
    end: bool = False  # End of event
    volume: int = 10  # Power level in dBm0 (0-63)
    duration: int = 0  # Duration in timestamp units
    
    @property
    def digit(self) -> str:
        """Get DTMF digit character."""
        return DTMF_TO_CHAR.get(self.event, "?")
    
    @classmethod
    def from_char(cls, char: str, **kwargs) -> "DTMFEvent":
        """Create DTMF event from character."""
        event_code = CHAR_TO_DTMF.get(char)
        if event_code is None:
            raise ValueError(f"Invalid DTMF character: {char}")
        return cls(event=event_code, **kwargs)
    
    @classmethod
    def parse(cls, data: bytes) -> "DTMFEvent":
        """
        Parse DTMF event from payload bytes.
        
        Args:
            data: 4-byte event payload
            
        Returns:
            Parsed DTMFEvent
        """
        if len(data) < 4:
            raise ValueError(f"DTMF payload too short: {len(data)} bytes")
        
        event, flags_volume, duration = struct.unpack("!BBH", data[:4])
        
        end = bool((flags_volume >> 7) & 0x01)
        volume = flags_volume & 0x3F
        
        return cls(
            event=event,
            end=end,
            volume=volume,
            duration=duration,
        )
    
    def serialize(self) -> bytes:
        """
        Serialize DTMF event to payload bytes.
        
        Returns:
            4-byte event payload
        """
        flags_volume = ((1 if self.end else 0) << 7) | (self.volume & 0x3F)
        
        return struct.pack(
            "!BBH",
            self.event & 0xFF,
            flags_volume,
            self.duration & 0xFFFF,
        )
    
    def __repr__(self) -> str:
        return f"DTMFEvent(digit='{self.digit}', end={self.end}, duration={self.duration})"


class DTMFEventStream:
    """
    Generates DTMF event packets for RTP transmission.
    
    Per RFC 2833, DTMF is sent as:
    1. Multiple packets with same timestamp during digit
    2. End packets with E=1 sent 3 times
    3. RTP marker bit set on first packet
    
    Example:
        stream = DTMFEventStream(payload_type=101, clock_rate=8000)
        
        # Send digit "5" for 160ms
        for packet_data in stream.generate_digit("5", duration_ms=160):
            rtp_session.send(packet_data)
    """
    
    __slots__ = (
        "_payload_type",
        "_clock_rate",
        "_packet_interval_ms",
    )
    
    def __init__(
        self,
        payload_type: int = 101,
        clock_rate: int = 8000,
        packet_interval_ms: int = 20,
    ):
        self._payload_type = payload_type
        self._clock_rate = clock_rate
        self._packet_interval_ms = packet_interval_ms
    
    def generate_digit(
        self,
        digit: str,
        duration_ms: int = 160,
        volume: int = 10,
    ) -> list[tuple[bytes, bool]]:
        """
        Generate DTMF event packets for a digit.
        
        Args:
            digit: DTMF digit character
            duration_ms: Total duration in milliseconds
            volume: Volume level (0-63)
            
        Returns:
            List of (payload_bytes, is_first_packet) tuples
        """
        event_code = CHAR_TO_DTMF.get(digit)
        if event_code is None:
            raise ValueError(f"Invalid DTMF digit: {digit}")
        
        packets = []
        samples_per_ms = self._clock_rate // 1000
        interval_samples = self._packet_interval_ms * samples_per_ms
        total_samples = duration_ms * samples_per_ms
        
        # Generate packets during digit
        current_duration = 0
        is_first = True
        
        while current_duration < total_samples:
            current_duration += interval_samples
            if current_duration > total_samples:
                current_duration = total_samples
            
            event = DTMFEvent(
                event=event_code,
                end=False,
                volume=volume,
                duration=current_duration,
            )
            packets.append((event.serialize(), is_first))
            is_first = False
        
        # Generate 3 end packets (per RFC 2833)
        for _ in range(3):
            event = DTMFEvent(
                event=event_code,
                end=True,
                volume=volume,
                duration=total_samples,
            )
            packets.append((event.serialize(), False))
        
        return packets


