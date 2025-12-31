"""
SDP Parser

RFC 4566 compliant SDP parsing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...exceptions import SDPParseError
from ...types import CodecType, MediaDirection


@dataclass(slots=True)
class MediaDescription:
    """SDP media description (m= line and associated attributes)."""
    
    media_type: str  # "audio", "video", etc.
    port: int
    protocol: str  # "RTP/AVP", "RTP/SAVP", etc.
    formats: list[int] = field(default_factory=list)  # Payload types
    
    # Connection info (can override session-level)
    connection_address: str | None = None
    
    # Media attributes
    rtpmap: dict[int, tuple[str, int]] = field(default_factory=dict)  # PT -> (codec, clock_rate)
    fmtp: dict[int, str] = field(default_factory=dict)  # PT -> format params
    direction: MediaDirection = MediaDirection.SENDRECV
    ptime: int | None = None
    
    # Additional attributes
    attributes: dict[str, str] = field(default_factory=dict)
    
    def get_codec_name(self, payload_type: int) -> str | None:
        """Get codec name for payload type."""
        if payload_type in self.rtpmap:
            return self.rtpmap[payload_type][0]
        # Standard payload types
        if payload_type == 0:
            return "PCMU"
        if payload_type == 8:
            return "PCMA"
        if payload_type == 9:
            return "G722"
        if payload_type == 18:
            return "G729"
        return None
    
    def get_clock_rate(self, payload_type: int) -> int:
        """Get clock rate for payload type."""
        if payload_type in self.rtpmap:
            return self.rtpmap[payload_type][1]
        # Standard clock rates
        if payload_type in (0, 8, 18):
            return 8000
        if payload_type == 9:
            return 8000  # G.722 uses 8kHz in SDP (actual is 16kHz)
        return 8000


@dataclass(slots=True)
class SDPMessage:
    """
    Parsed SDP message.
    
    Contains session-level and media-level descriptions.
    """
    
    # Session description (required)
    version: int = 0
    origin_username: str = "-"
    origin_session_id: str = "0"
    origin_session_version: str = "0"
    origin_network_type: str = "IN"
    origin_address_type: str = "IP4"
    origin_address: str = "0.0.0.0"
    session_name: str = "-"
    
    # Session info
    session_info: str | None = None
    uri: str | None = None
    email: str | None = None
    phone: str | None = None
    
    # Connection (session-level)
    connection_network_type: str = "IN"
    connection_address_type: str = "IP4"
    connection_address: str = "0.0.0.0"
    
    # Timing
    timing_start: int = 0
    timing_stop: int = 0
    
    # Attributes
    attributes: dict[str, str] = field(default_factory=dict)
    
    # Media descriptions
    media: list[MediaDescription] = field(default_factory=list)
    
    # Raw SDP for debugging
    raw: bytes | None = None
    
    @property
    def audio_media(self) -> MediaDescription | None:
        """Get first audio media description."""
        for m in self.media:
            if m.media_type == "audio":
                return m
        return None
    
    @property
    def video_media(self) -> MediaDescription | None:
        """Get first video media description."""
        for m in self.media:
            if m.media_type == "video":
                return m
        return None
    
    def get_audio_address(self) -> tuple[str, int] | None:
        """Get audio RTP address (IP, port)."""
        audio = self.audio_media
        if not audio:
            return None
        
        addr = audio.connection_address or self.connection_address
        return (addr, audio.port)
    
    def get_audio_codec(self) -> tuple[int, str, int] | None:
        """Get primary audio codec (payload_type, name, clock_rate)."""
        audio = self.audio_media
        if not audio or not audio.formats:
            return None
        
        pt = audio.formats[0]
        name = audio.get_codec_name(pt) or "unknown"
        rate = audio.get_clock_rate(pt)
        return (pt, name, rate)


class SDPParser:
    """
    SDP message parser.
    
    Example:
        parser = SDPParser()
        sdp = parser.parse(sdp_bytes)
        
        audio = sdp.audio_media
        if audio:
            print(f"Audio: {audio.port}, codecs: {audio.formats}")
    """
    
    __slots__ = ()
    
    def parse(self, data: bytes) -> SDPMessage:
        """
        Parse SDP from bytes.
        
        Args:
            data: Raw SDP bytes
            
        Returns:
            Parsed SDPMessage
            
        Raises:
            SDPParseError: If SDP cannot be parsed
        """
        if not data:
            raise SDPParseError("Empty SDP")
        
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            raise SDPParseError("Invalid SDP encoding")
        
        sdp = SDPMessage(raw=data)
        current_media: MediaDescription | None = None
        
        for line in text.replace("\r\n", "\n").split("\n"):
            line = line.strip()
            if not line or len(line) < 2 or line[1] != "=":
                continue
            
            line_type = line[0]
            value = line[2:]
            
            try:
                if line_type == "v":
                    sdp.version = int(value)
                
                elif line_type == "o":
                    self._parse_origin(sdp, value)
                
                elif line_type == "s":
                    sdp.session_name = value
                
                elif line_type == "i":
                    if current_media:
                        current_media.attributes["info"] = value
                    else:
                        sdp.session_info = value
                
                elif line_type == "u":
                    sdp.uri = value
                
                elif line_type == "e":
                    sdp.email = value
                
                elif line_type == "p":
                    sdp.phone = value
                
                elif line_type == "c":
                    self._parse_connection(sdp, current_media, value)
                
                elif line_type == "t":
                    parts = value.split()
                    if len(parts) >= 2:
                        sdp.timing_start = int(parts[0])
                        sdp.timing_stop = int(parts[1])
                
                elif line_type == "m":
                    current_media = self._parse_media(value)
                    sdp.media.append(current_media)
                
                elif line_type == "a":
                    self._parse_attribute(sdp, current_media, value)
            
            except (ValueError, IndexError) as e:
                # Skip malformed lines
                continue
        
        return sdp
    
    def _parse_origin(self, sdp: SDPMessage, value: str) -> None:
        """Parse o= line."""
        parts = value.split()
        if len(parts) >= 6:
            sdp.origin_username = parts[0]
            sdp.origin_session_id = parts[1]
            sdp.origin_session_version = parts[2]
            sdp.origin_network_type = parts[3]
            sdp.origin_address_type = parts[4]
            sdp.origin_address = parts[5]
    
    def _parse_connection(
        self,
        sdp: SDPMessage,
        media: MediaDescription | None,
        value: str,
    ) -> None:
        """Parse c= line."""
        parts = value.split()
        if len(parts) >= 3:
            addr = parts[2].split("/")[0]  # Remove TTL/multicast count
            
            if media:
                media.connection_address = addr
            else:
                sdp.connection_network_type = parts[0]
                sdp.connection_address_type = parts[1]
                sdp.connection_address = addr
    
    def _parse_media(self, value: str) -> MediaDescription:
        """Parse m= line."""
        parts = value.split()
        
        media_type = parts[0] if parts else "audio"
        
        port = 0
        if len(parts) > 1:
            port_str = parts[1].split("/")[0]  # Remove port count
            port = int(port_str)
        
        protocol = parts[2] if len(parts) > 2 else "RTP/AVP"
        
        formats = []
        for fmt in parts[3:]:
            try:
                formats.append(int(fmt))
            except ValueError:
                pass
        
        return MediaDescription(
            media_type=media_type,
            port=port,
            protocol=protocol,
            formats=formats,
        )
    
    def _parse_attribute(
        self,
        sdp: SDPMessage,
        media: MediaDescription | None,
        value: str,
    ) -> None:
        """Parse a= line."""
        # Split into name:value
        if ":" in value:
            name, attr_value = value.split(":", 1)
        else:
            name = value
            attr_value = ""
        
        # Direction attributes
        if name in ("sendrecv", "sendonly", "recvonly", "inactive"):
            if media:
                media.direction = MediaDirection(name)
            return
        
        # rtpmap
        if name == "rtpmap" and media:
            # format: payload_type codec/clock_rate[/channels]
            parts = attr_value.split(None, 1)
            if len(parts) >= 2:
                try:
                    pt = int(parts[0])
                    codec_parts = parts[1].split("/")
                    codec_name = codec_parts[0]
                    clock_rate = int(codec_parts[1]) if len(codec_parts) > 1 else 8000
                    media.rtpmap[pt] = (codec_name, clock_rate)
                except (ValueError, IndexError):
                    pass
            return
        
        # fmtp
        if name == "fmtp" and media:
            parts = attr_value.split(None, 1)
            if len(parts) >= 2:
                try:
                    pt = int(parts[0])
                    media.fmtp[pt] = parts[1]
                except ValueError:
                    pass
            return
        
        # ptime
        if name == "ptime" and media:
            try:
                media.ptime = int(attr_value)
            except ValueError:
                pass
            return
        
        # Store in appropriate attributes dict
        if media:
            media.attributes[name] = attr_value
        else:
            sdp.attributes[name] = attr_value


def parse_sdp(data: bytes) -> SDPMessage:
    """Convenience function to parse SDP."""
    return SDPParser().parse(data)


