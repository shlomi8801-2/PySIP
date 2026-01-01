"""
RTCP - RTP Control Protocol

RFC 3550 compliant RTCP packet handling for quality metrics and synchronization.
"""

from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING


class RTCPType(IntEnum):
    """RTCP packet types per RFC 3550."""
    
    SR = 200    # Sender Report
    RR = 201    # Receiver Report
    SDES = 202  # Source Description
    BYE = 203   # Goodbye
    APP = 204   # Application-defined


class SDESType(IntEnum):
    """SDES item types per RFC 3550."""
    
    END = 0      # End of SDES list
    CNAME = 1    # Canonical name
    NAME = 2     # User name
    EMAIL = 3    # Email
    PHONE = 4    # Phone number
    LOC = 5      # Geographic location
    TOOL = 6     # Application or tool name
    NOTE = 7     # Notice/status
    PRIV = 8     # Private extension


@dataclass(slots=True)
class ReportBlock:
    """
    RTCP Report Block (used in SR and RR).
    
    Contains reception quality information for a single source.
    """
    
    ssrc: int                  # SSRC of source being reported
    fraction_lost: int = 0     # Fraction of packets lost (0-255)
    cumulative_lost: int = 0   # Cumulative packets lost (24-bit signed)
    highest_seq: int = 0       # Extended highest sequence number received
    jitter: int = 0            # Interarrival jitter
    lsr: int = 0               # Last SR timestamp (middle 32 bits of NTP)
    dlsr: int = 0              # Delay since last SR (1/65536 seconds)
    
    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> "ReportBlock":
        """Parse a report block from bytes."""
        if len(data) < offset + 24:
            raise ValueError("Report block too short")
        
        ssrc, loss_info, highest_seq, jitter, lsr, dlsr = struct.unpack_from(
            "!IIIIII", data, offset
        )
        
        fraction_lost = (loss_info >> 24) & 0xFF
        cumulative_lost = loss_info & 0x00FFFFFF
        # Handle sign extension for 24-bit signed int
        if cumulative_lost & 0x800000:
            cumulative_lost -= 0x1000000
        
        return cls(
            ssrc=ssrc,
            fraction_lost=fraction_lost,
            cumulative_lost=cumulative_lost,
            highest_seq=highest_seq,
            jitter=jitter,
            lsr=lsr,
            dlsr=dlsr,
        )
    
    def serialize(self) -> bytes:
        """Serialize report block to bytes."""
        # Combine fraction lost and cumulative lost
        loss_info = ((self.fraction_lost & 0xFF) << 24) | (self.cumulative_lost & 0x00FFFFFF)
        
        return struct.pack(
            "!IIIIII",
            self.ssrc,
            loss_info,
            self.highest_seq,
            self.jitter,
            self.lsr,
            self.dlsr,
        )


@dataclass(slots=True)
class SenderReport:
    """
    RTCP Sender Report (SR) packet.
    
    Sent by sources that have sent RTP packets.
    """
    
    ssrc: int                               # Sender SSRC
    ntp_timestamp_msw: int = 0              # NTP timestamp (most significant word)
    ntp_timestamp_lsw: int = 0              # NTP timestamp (least significant word)
    rtp_timestamp: int = 0                  # RTP timestamp
    sender_packet_count: int = 0            # Total packets sent
    sender_octet_count: int = 0             # Total bytes sent
    report_blocks: list[ReportBlock] = field(default_factory=list)
    
    @property
    def ntp_timestamp(self) -> float:
        """Get NTP timestamp as float."""
        return self.ntp_timestamp_msw + self.ntp_timestamp_lsw / (2**32)
    
    @classmethod
    def parse(cls, data: bytes) -> "SenderReport":
        """Parse Sender Report from bytes (after common header)."""
        if len(data) < 24:
            raise ValueError("Sender Report too short")
        
        ssrc, ntp_msw, ntp_lsw, rtp_ts, pkt_count, octet_count = struct.unpack_from(
            "!IIIIII", data, 0
        )
        
        report_blocks = []
        offset = 24
        # Report count is in the common header, passed separately
        while offset + 24 <= len(data):
            block = ReportBlock.parse(data, offset)
            report_blocks.append(block)
            offset += 24
        
        return cls(
            ssrc=ssrc,
            ntp_timestamp_msw=ntp_msw,
            ntp_timestamp_lsw=ntp_lsw,
            rtp_timestamp=rtp_ts,
            sender_packet_count=pkt_count,
            sender_octet_count=octet_count,
            report_blocks=report_blocks,
        )
    
    def serialize(self) -> bytes:
        """Serialize Sender Report to bytes."""
        # Common header
        version = 2
        padding = 0
        rc = len(self.report_blocks)
        pt = RTCPType.SR
        length = 6 + 6 * rc  # in 32-bit words minus one
        
        header = struct.pack(
            "!BBH",
            (version << 6) | (padding << 5) | rc,
            pt,
            length,
        )
        
        sender_info = struct.pack(
            "!IIIIII",
            self.ssrc,
            self.ntp_timestamp_msw,
            self.ntp_timestamp_lsw,
            self.rtp_timestamp,
            self.sender_packet_count,
            self.sender_octet_count,
        )
        
        blocks = b"".join(block.serialize() for block in self.report_blocks)
        
        return header + sender_info + blocks


@dataclass(slots=True)
class ReceiverReport:
    """
    RTCP Receiver Report (RR) packet.
    
    Sent by receivers that haven't sent RTP packets.
    """
    
    ssrc: int                               # Reporter SSRC
    report_blocks: list[ReportBlock] = field(default_factory=list)
    
    @classmethod
    def parse(cls, data: bytes) -> "ReceiverReport":
        """Parse Receiver Report from bytes (after common header)."""
        if len(data) < 4:
            raise ValueError("Receiver Report too short")
        
        ssrc = struct.unpack_from("!I", data, 0)[0]
        
        report_blocks = []
        offset = 4
        while offset + 24 <= len(data):
            block = ReportBlock.parse(data, offset)
            report_blocks.append(block)
            offset += 24
        
        return cls(ssrc=ssrc, report_blocks=report_blocks)
    
    def serialize(self) -> bytes:
        """Serialize Receiver Report to bytes."""
        version = 2
        padding = 0
        rc = len(self.report_blocks)
        pt = RTCPType.RR
        length = 1 + 6 * rc
        
        header = struct.pack(
            "!BBH",
            (version << 6) | (padding << 5) | rc,
            pt,
            length,
        )
        
        ssrc_data = struct.pack("!I", self.ssrc)
        blocks = b"".join(block.serialize() for block in self.report_blocks)
        
        return header + ssrc_data + blocks


@dataclass(slots=True)
class SDESItem:
    """SDES item (type, value pair)."""
    
    item_type: SDESType
    value: str
    
    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> tuple["SDESItem | None", int]:
        """
        Parse an SDES item from bytes.
        
        Args:
            data: Raw bytes
            offset: Starting offset
            
        Returns:
            Tuple of (SDESItem or None if END, bytes consumed)
        """
        if offset >= len(data):
            return None, 0
        
        item_type = data[offset]
        
        # END item (type 0) marks end of chunk
        if item_type == SDESType.END:
            return None, 1
        
        if offset + 1 >= len(data):
            return None, 0
        
        length = data[offset + 1]
        
        if offset + 2 + length > len(data):
            return None, 0
        
        try:
            value = data[offset + 2:offset + 2 + length].decode("utf-8")
        except UnicodeDecodeError:
            value = data[offset + 2:offset + 2 + length].decode("latin-1")
        
        return cls(item_type=SDESType(item_type), value=value), 2 + length
    
    def serialize(self) -> bytes:
        """Serialize SDES item to bytes."""
        value_bytes = self.value.encode("utf-8")[:255]
        return struct.pack("!BB", self.item_type, len(value_bytes)) + value_bytes


@dataclass(slots=True)
class SDESChunk:
    """SDES chunk for one SSRC."""
    
    ssrc: int
    items: list[SDESItem] = field(default_factory=list)
    
    @classmethod
    def parse(cls, data: bytes, offset: int = 0) -> tuple["SDESChunk | None", int]:
        """
        Parse an SDES chunk from bytes.
        
        Args:
            data: Raw bytes
            offset: Starting offset
            
        Returns:
            Tuple of (SDESChunk, bytes consumed)
        """
        start_offset = offset
        
        if offset + 4 > len(data):
            return None, 0
        
        ssrc = struct.unpack_from("!I", data, offset)[0]
        offset += 4
        
        items = []
        while offset < len(data):
            item, consumed = SDESItem.parse(data, offset)
            if item is None:
                # END item or error - skip to 32-bit boundary
                offset += consumed
                break
            items.append(item)
            offset += consumed
        
        # Skip padding to 32-bit boundary
        padding = (4 - (offset - start_offset) % 4) % 4
        offset += padding
        
        return cls(ssrc=ssrc, items=items), offset - start_offset
    
    def serialize(self) -> bytes:
        """Serialize SDES chunk to bytes."""
        data = struct.pack("!I", self.ssrc)
        for item in self.items:
            data += item.serialize()
        # End with null item and pad to 32-bit boundary
        data += b"\x00"
        padding = (4 - len(data) % 4) % 4
        data += b"\x00" * padding
        return data
    
    def get_cname(self) -> str | None:
        """Get CNAME item value if present."""
        for item in self.items:
            if item.item_type == SDESType.CNAME:
                return item.value
        return None


@dataclass(slots=True)
class SourceDescription:
    """
    RTCP Source Description (SDES) packet.
    
    Contains CNAME and other source identification.
    """
    
    chunks: list[SDESChunk] = field(default_factory=list)
    
    @classmethod
    def parse(cls, data: bytes, source_count: int = 0) -> "SourceDescription":
        """
        Parse Source Description from bytes (after common header).
        
        Args:
            data: Raw bytes (payload after RTCP header)
            source_count: Number of chunks (SC field from header)
        """
        chunks = []
        offset = 0
        
        # Parse up to source_count chunks, or all available data
        chunks_parsed = 0
        while offset < len(data):
            if source_count > 0 and chunks_parsed >= source_count:
                break
            
            chunk, consumed = SDESChunk.parse(data, offset)
            if chunk is None or consumed == 0:
                break
            
            chunks.append(chunk)
            offset += consumed
            chunks_parsed += 1
        
        return cls(chunks=chunks)
    
    def serialize(self) -> bytes:
        """Serialize SDES to bytes."""
        chunks_data = b"".join(chunk.serialize() for chunk in self.chunks)
        
        version = 2
        padding = 0
        sc = len(self.chunks)
        pt = RTCPType.SDES
        length = len(chunks_data) // 4
        
        header = struct.pack(
            "!BBH",
            (version << 6) | (padding << 5) | sc,
            pt,
            length,
        )
        
        return header + chunks_data
    
    def get_cname(self, ssrc: int) -> str | None:
        """Get CNAME for a specific SSRC."""
        for chunk in self.chunks:
            if chunk.ssrc == ssrc:
                return chunk.get_cname()
        return None


@dataclass(slots=True)
class Goodbye:
    """
    RTCP Goodbye (BYE) packet.
    
    Indicates a source is leaving the session.
    """
    
    ssrc_list: list[int] = field(default_factory=list)
    reason: str = ""
    
    def serialize(self) -> bytes:
        """Serialize BYE to bytes."""
        ssrc_data = b"".join(struct.pack("!I", ssrc) for ssrc in self.ssrc_list)
        
        reason_bytes = b""
        if self.reason:
            reason_encoded = self.reason.encode("utf-8")[:255]
            reason_bytes = struct.pack("!B", len(reason_encoded)) + reason_encoded
            # Pad to 32-bit boundary
            padding = (4 - len(reason_bytes) % 4) % 4
            reason_bytes += b"\x00" * padding
        
        total_length = len(ssrc_data) + len(reason_bytes)
        
        version = 2
        padding = 0
        sc = len(self.ssrc_list)
        pt = RTCPType.BYE
        length = total_length // 4
        
        header = struct.pack(
            "!BBH",
            (version << 6) | (padding << 5) | sc,
            pt,
            length,
        )
        
        return header + ssrc_data + reason_bytes


def get_ntp_timestamp() -> tuple[int, int]:
    """
    Get current NTP timestamp as (MSW, LSW).
    
    NTP timestamp is seconds since Jan 1, 1900.
    """
    # Convert Unix time to NTP time (add 70 years in seconds)
    NTP_EPOCH_OFFSET = 2208988800
    
    now = time.time() + NTP_EPOCH_OFFSET
    msw = int(now)
    lsw = int((now - msw) * (2**32))
    
    return msw, lsw


def ntp_to_compact(msw: int, lsw: int) -> int:
    """Convert NTP timestamp to compact 32-bit form (middle 32 bits)."""
    return ((msw & 0xFFFF) << 16) | ((lsw >> 16) & 0xFFFF)


def parse_rtcp_packet(data: bytes) -> SenderReport | ReceiverReport | SourceDescription | Goodbye:
    """
    Parse an RTCP packet from bytes.
    
    Args:
        data: Raw RTCP packet bytes
        
    Returns:
        Parsed RTCP packet
    """
    if len(data) < 4:
        raise ValueError("RTCP packet too short")
    
    first_byte, pt = struct.unpack_from("!BB", data, 0)
    
    # Extract fields from first byte
    version = (first_byte >> 6) & 0x03
    if version != 2:
        raise ValueError(f"Invalid RTCP version: {version}")
    
    rc = first_byte & 0x1F  # Report count or subtype
    
    # Parse based on packet type
    payload = data[4:]  # Skip common header
    
    if pt == RTCPType.SR:
        return SenderReport.parse(payload)
    elif pt == RTCPType.RR:
        return ReceiverReport.parse(payload)
    elif pt == RTCPType.SDES:
        return SourceDescription.parse(payload, source_count=rc)
    elif pt == RTCPType.BYE:
        ssrc_list = []
        for i in range(rc):
            if len(payload) >= (i + 1) * 4:
                ssrc = struct.unpack_from("!I", payload, i * 4)[0]
                ssrc_list.append(ssrc)
        return Goodbye(ssrc_list=ssrc_list)
    else:
        raise ValueError(f"Unknown RTCP packet type: {pt}")

