"""
SDP Builder

RFC 4566 compliant SDP building.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ...types import CodecType, MediaDirection
from .parser import MediaDescription, SDPMessage


@dataclass(slots=True)
class AudioCodecOffer:
    """Audio codec to offer in SDP."""
    
    payload_type: int
    name: str
    clock_rate: int = 8000
    channels: int = 1
    fmtp: str | None = None


# Common codec offers
PCMU_OFFER = AudioCodecOffer(CodecType.PCMU, "PCMU", 8000)
PCMA_OFFER = AudioCodecOffer(CodecType.PCMA, "PCMA", 8000)
G722_OFFER = AudioCodecOffer(CodecType.G722, "G722", 8000)
TELEPHONE_EVENT_OFFER = AudioCodecOffer(101, "telephone-event", 8000, fmtp="0-16")

# Codec name to offer mapping
CODEC_BY_NAME: dict[str, AudioCodecOffer] = {
    "pcmu": PCMU_OFFER,
    "pcma": PCMA_OFFER,
    "g722": G722_OFFER,
    "telephone-event": TELEPHONE_EVENT_OFFER,
}


class SDPBuilder:
    """
    SDP message builder.
    
    Example:
        builder = SDPBuilder(local_ip="192.168.1.100")
        
        sdp = builder.create_offer(
            audio_port=10000,
            codecs=[PCMU_OFFER, PCMA_OFFER, TELEPHONE_EVENT_OFFER],
        )
        
        sdp_bytes = builder.serialize(sdp)
    """
    
    __slots__ = (
        "_local_ip",
        "_username",
        "_session_name",
        "_session_id",
        "_session_version",
    )
    
    def __init__(
        self,
        local_ip: str = "0.0.0.0",
        username: str = "-",
        session_name: str = "PySIP",
    ):
        self._local_ip = local_ip
        self._username = username
        self._session_name = session_name
        self._session_id = str(int(time.time()))
        self._session_version = str(int(time.time()))
    
    def create_offer(
        self,
        audio_port: int,
        codecs: list[AudioCodecOffer | str] | None = None,
        direction: MediaDirection = MediaDirection.SENDRECV,
        ptime: int = 20,
        rtcp_mux: bool = False,
    ) -> SDPMessage:
        """
        Create SDP offer for outbound call.
        
        Args:
            audio_port: Local RTP port
            codecs: Audio codecs to offer. Can be:
                    - List of AudioCodecOffer objects
                    - List of codec names as strings (e.g., ["pcmu", "pcma"])
                    - None (default: PCMU, PCMA, telephone-event)
            direction: Media direction
            ptime: Packetization time in ms
            rtcp_mux: Enable RTCP-MUX (RFC 5761) - RTP/RTCP on same port
            
        Returns:
            SDPMessage for offer
            
        Example:
            # Using codec names (recommended for simple cases)
            sdp = builder.create_offer(audio_port=10000, codecs=["pcmu", "pcma"])
            
            # Using AudioCodecOffer objects (for custom configurations)
            sdp = builder.create_offer(audio_port=10000, codecs=[PCMU_OFFER])
        """
        if codecs is None:
            codecs = [PCMU_OFFER, PCMA_OFFER, TELEPHONE_EVENT_OFFER]
        else:
            # Convert string names to AudioCodecOffer objects
            resolved_codecs: list[AudioCodecOffer] = []
            for codec in codecs:
                if isinstance(codec, str):
                    codec_lower = codec.lower()
                    if codec_lower in CODEC_BY_NAME:
                        resolved_codecs.append(CODEC_BY_NAME[codec_lower])
                else:
                    resolved_codecs.append(codec)
            
            # Always include telephone-event for DTMF support
            has_telephone_event = any(
                (isinstance(c, AudioCodecOffer) and c.name.lower() == "telephone-event")
                for c in resolved_codecs
            )
            if not has_telephone_event:
                resolved_codecs.append(TELEPHONE_EVENT_OFFER)
            
            codecs = resolved_codecs
        
        # Create audio media description
        audio_media = MediaDescription(
            media_type="audio",
            port=audio_port,
            protocol="RTP/AVP",
            formats=[c.payload_type for c in codecs],
            direction=direction,
            ptime=ptime,
        )
        
        # Add rtpmap and fmtp for each codec
        for codec in codecs:
            audio_media.rtpmap[codec.payload_type] = (codec.name, codec.clock_rate)
            if codec.fmtp:
                audio_media.fmtp[codec.payload_type] = codec.fmtp
        
        # Add RTCP attributes
        if rtcp_mux:
            audio_media.attributes["rtcp-mux"] = ""
        else:
            # RFC 3605 - explicit RTCP port
            audio_media.attributes["rtcp"] = str(audio_port + 1)
        
        return SDPMessage(
            version=0,
            origin_username=self._username,
            origin_session_id=self._session_id,
            origin_session_version=self._session_version,
            origin_network_type="IN",
            origin_address_type="IP4",
            origin_address=self._local_ip,
            session_name=self._session_name,
            connection_network_type="IN",
            connection_address_type="IP4",
            connection_address=self._local_ip,
            timing_start=0,
            timing_stop=0,
            media=[audio_media],
        )
    
    def create_answer(
        self,
        offer: SDPMessage,
        audio_port: int,
        selected_codec: int | None = None,
        direction: MediaDirection | None = None,
        rtcp_mux: bool | None = None,
    ) -> SDPMessage:
        """
        Create SDP answer from offer.
        
        Args:
            offer: Received SDP offer
            audio_port: Local RTP port
            selected_codec: Payload type to accept (default: first offered)
            direction: Override direction
            rtcp_mux: Enable RTCP-MUX. If None, mirrors offer's rtcp-mux attribute.
            
        Returns:
            SDPMessage for answer
        """
        offer_audio = offer.audio_media
        if not offer_audio:
            raise ValueError("Offer has no audio media")
        
        # Select codec
        if selected_codec is None:
            # Select first supported codec
            for pt in offer_audio.formats:
                if pt in (CodecType.PCMU, CodecType.PCMA):
                    selected_codec = pt
                    break
            if selected_codec is None and offer_audio.formats:
                selected_codec = offer_audio.formats[0]
        
        if selected_codec is None:
            raise ValueError("No codec to select")
        
        # Determine direction
        if direction is None:
            # Mirror offer direction
            if offer_audio.direction == MediaDirection.SENDONLY:
                direction = MediaDirection.RECVONLY
            elif offer_audio.direction == MediaDirection.RECVONLY:
                direction = MediaDirection.SENDONLY
            else:
                direction = offer_audio.direction
        
        # Build answer media
        answer_formats = [selected_codec]
        
        # Include telephone-event if offered
        for pt in offer_audio.formats:
            if pt >= 96 and pt != selected_codec:  # Dynamic payload types
                codec_name = offer_audio.get_codec_name(pt)
                if codec_name and "telephone-event" in codec_name.lower():
                    answer_formats.append(pt)
                    break
        
        audio_media = MediaDescription(
            media_type="audio",
            port=audio_port,
            protocol=offer_audio.protocol,
            formats=answer_formats,
            direction=direction,
            ptime=offer_audio.ptime or 20,
        )
        
        # Copy rtpmap for selected codecs
        for pt in answer_formats:
            if pt in offer_audio.rtpmap:
                audio_media.rtpmap[pt] = offer_audio.rtpmap[pt]
            elif pt == CodecType.PCMU:
                audio_media.rtpmap[pt] = ("PCMU", 8000)
            elif pt == CodecType.PCMA:
                audio_media.rtpmap[pt] = ("PCMA", 8000)
        
        # Copy fmtp
        for pt in answer_formats:
            if pt in offer_audio.fmtp:
                audio_media.fmtp[pt] = offer_audio.fmtp[pt]
        
        # Handle RTCP-MUX (RFC 5761)
        # If rtcp_mux is None, mirror the offer's setting
        if rtcp_mux is None:
            rtcp_mux = "rtcp-mux" in offer_audio.attributes
        
        if rtcp_mux:
            audio_media.attributes["rtcp-mux"] = ""
        else:
            # RFC 3605 - explicit RTCP port
            audio_media.attributes["rtcp"] = str(audio_port + 1)
        
        return SDPMessage(
            version=0,
            origin_username=self._username,
            origin_session_id=self._session_id,
            origin_session_version=self._session_version,
            origin_network_type="IN",
            origin_address_type="IP4",
            origin_address=self._local_ip,
            session_name=self._session_name,
            connection_network_type="IN",
            connection_address_type="IP4",
            connection_address=self._local_ip,
            timing_start=0,
            timing_stop=0,
            media=[audio_media],
        )
    
    def serialize(self, sdp: SDPMessage) -> bytes:
        """
        Serialize SDP to bytes.
        
        Args:
            sdp: SDPMessage to serialize
            
        Returns:
            SDP as bytes
        """
        lines = []
        
        # Version
        lines.append(f"v={sdp.version}")
        
        # Origin
        lines.append(
            f"o={sdp.origin_username} {sdp.origin_session_id} "
            f"{sdp.origin_session_version} {sdp.origin_network_type} "
            f"{sdp.origin_address_type} {sdp.origin_address}"
        )
        
        # Session name
        lines.append(f"s={sdp.session_name}")
        
        # Connection (session-level)
        lines.append(
            f"c={sdp.connection_network_type} {sdp.connection_address_type} "
            f"{sdp.connection_address}"
        )
        
        # Timing
        lines.append(f"t={sdp.timing_start} {sdp.timing_stop}")
        
        # Session attributes
        for name, value in sdp.attributes.items():
            if value:
                lines.append(f"a={name}:{value}")
            else:
                lines.append(f"a={name}")
        
        # Media descriptions
        for media in sdp.media:
            # m= line - ensure formats are integers (not enum names)
            formats_str = " ".join(str(int(f)) for f in media.formats)
            lines.append(f"m={media.media_type} {media.port} {media.protocol} {formats_str}")
            
            # Media-level connection (if different from session)
            if media.connection_address:
                lines.append(f"c=IN IP4 {media.connection_address}")
            
            # rtpmap
            for pt, (codec, rate) in media.rtpmap.items():
                lines.append(f"a=rtpmap:{pt} {codec}/{rate}")
            
            # fmtp
            for pt, params in media.fmtp.items():
                lines.append(f"a=fmtp:{pt} {params}")
            
            # ptime
            if media.ptime:
                lines.append(f"a=ptime:{media.ptime}")
            
            # Direction
            lines.append(f"a={media.direction.value}")
            
            # Other attributes
            for name, value in media.attributes.items():
                if name not in ("info",):  # Skip special ones
                    if value:
                        lines.append(f"a={name}:{value}")
                    else:
                        lines.append(f"a={name}")
        
        return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def build_sdp_offer(
    local_ip: str,
    audio_port: int,
    codecs: list[AudioCodecOffer] | None = None,
) -> bytes:
    """Convenience function to build SDP offer."""
    builder = SDPBuilder(local_ip=local_ip)
    sdp = builder.create_offer(audio_port=audio_port, codecs=codecs)
    return builder.serialize(sdp)


