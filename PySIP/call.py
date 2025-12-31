"""
Call - SIP Call with Media Operations

Represents a single SIP call with media handling.
"""

from __future__ import annotations

import asyncio
import logging
import random
import string
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

from .exceptions import (
    CallFailedError,
    CallRejectedError,
    CallStateError,
    CallTimeoutError,
)
from .media.codecs import PCMACodec, PCMUCodec
from .media.player import AudioPlayer, PlaybackHandle
from .media.stream import AudioStream, TELEPHONY_FORMAT
from .protocol.rtp import RTPPacket
from .protocol.sdp import SDPBuilder, SDPParser
from .protocol.sip import DigestAuth, SIPBuilder, SIPParser
from .protocol.sip.builder import serialize_request, serialize_response
from .protocol.sip.message import SIPRequest, SIPResponse
from .transport.rtp import RTPSession
from .types import (
    Address,
    CallDirection,
    CallState,
    CodecType,
    DTMFMode,
    HangupCause,
    RTPConfig,
    SIPMethod,
)

if TYPE_CHECKING:
    from .features.amd import AMDResult
    from .features.recording import Recording
    from .transport import UDPTransport

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class GatherResult:
    """Result of DTMF gather operation."""
    
    digits: str
    terminated_by: Literal["max_digits", "timeout", "finish_key", "hangup"] = "timeout"


class Call:
    """
    Represents a SIP call with media operations.
    
    Features:
    - Outbound and inbound call handling
    - Audio playback (play, say)
    - DTMF detection and sending
    - Call recording
    - AMD (Answering Machine Detection)
    - Call transfer
    
    Example (outbound):
        call = client.make_call("sip:bob@example.com")
        await call.start()
        
        await call.say("Hello, this is a test call")
        digits = await call.gather(max_digits=4, timeout=10)
        
        await call.hangup()
    
    Example (inbound):
        @client.on_incoming_call
        async def handle(call):
            await call.answer()
            await call.play("welcome.wav")
            await call.hangup()
    """
    
    __slots__ = (
        "_transport",
        "_local_ip",
        "_local_port",
        "_rtp_port",
        "_to_uri",
        "_from_uri",
        "_direction",
        "_server_address",
        "_username",
        "_password",
        "_user_agent",
        "_state",
        "_call_id",
        "_local_tag",
        "_remote_tag",
        "_dialog_id",
        "_cseq",
        "_sip_builder",
        "_rtp_session",
        "_codec",
        "_audio_player",
        "_invite_request",
        "_remote_sdp",
        "_local_sdp",
        "_dtmf_buffer",
        "_dtmf_event",
        "_on_dtmf",
        "_on_hangup",
        "_on_amd_result",
        "_created_at",
        "_answered_at",
        "_ended_at",
        "_hangup_cause",
        "_remote_address",
        "_incoming_invite",
    )
    
    def __init__(
        self,
        transport: "UDPTransport",
        local_ip: str,
        local_port: int,
        rtp_port: int,
        direction: Literal["inbound", "outbound"] = "outbound",
        to_uri: str | None = None,
        from_uri: str | None = None,
        server_address: Address | None = None,
        username: str | None = None,
        password: str | None = None,
        user_agent: str = "PySIP/2.0",
        incoming_invite: SIPRequest | None = None,
        remote_address: Address | None = None,
    ):
        self._transport = transport
        self._local_ip = local_ip
        self._local_port = local_port
        self._rtp_port = rtp_port
        self._to_uri = to_uri
        self._from_uri = from_uri
        self._direction = CallDirection(direction)
        self._server_address = server_address
        self._username = username
        self._password = password
        self._user_agent = user_agent
        self._incoming_invite = incoming_invite
        self._remote_address = remote_address
        
        # State
        self._state = CallState.IDLE
        self._call_id = self._generate_call_id()
        self._local_tag = self._generate_tag()
        self._remote_tag: str | None = None
        self._dialog_id: str | None = None
        self._cseq = 1
        
        # SIP builder
        self._sip_builder = SIPBuilder(
            local_ip=local_ip,
            local_port=local_port,
            user_agent=user_agent,
        )
        
        # RTP session
        self._rtp_session: RTPSession | None = None
        self._codec = PCMUCodec()  # Default to PCMU
        self._audio_player: AudioPlayer | None = None
        
        # SDP
        self._invite_request: SIPRequest | None = None
        self._remote_sdp: bytes | None = None
        self._local_sdp: bytes | None = None
        
        # DTMF
        self._dtmf_buffer: list[str] = []
        self._dtmf_event = asyncio.Event()
        self._on_dtmf: Callable[[str], Awaitable[None]] | None = None
        
        # Callbacks
        self._on_hangup: Callable[[str], None] | None = None
        self._on_amd_result: Callable[["AMDResult"], Awaitable[None]] | None = None
        
        # Timestamps
        self._created_at = time.time()
        self._answered_at: float | None = None
        self._ended_at: float | None = None
        self._hangup_cause = HangupCause.NORMAL
        
        # Handle incoming INVITE
        if incoming_invite:
            self._call_id = incoming_invite.call_id
            self._remote_tag = incoming_invite.from_tag
            if incoming_invite.body:
                self._remote_sdp = incoming_invite.body
    
    @staticmethod
    def _generate_call_id() -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
    
    @staticmethod
    def _generate_tag() -> str:
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    # === Properties ===
    
    @property
    def call_id(self) -> str:
        """Unique call identifier."""
        return self._call_id
    
    @property
    def state(self) -> CallState:
        """Current call state."""
        return self._state
    
    @property
    def direction(self) -> CallDirection:
        """Call direction (inbound/outbound)."""
        return self._direction
    
    @property
    def is_active(self) -> bool:
        """Check if call is active."""
        return self._state == CallState.ACTIVE
    
    @property
    def duration(self) -> float:
        """Call duration in seconds (0 if not answered)."""
        if not self._answered_at:
            return 0
        end = self._ended_at or time.time()
        return end - self._answered_at
    
    # === Event Handlers ===
    
    def on_dtmf(self, handler: Callable[[str], Awaitable[None]]) -> None:
        """Set DTMF digit handler."""
        self._on_dtmf = handler
    
    def on_hangup(self, handler: Callable[[str], None]) -> None:
        """Set hangup handler."""
        self._on_hangup = handler
    
    def on_amd_result(self, handler: Callable[["AMDResult"], Awaitable[None]]) -> None:
        """Set AMD result handler."""
        self._on_amd_result = handler
    
    # === Call Control ===
    
    async def start(self, timeout: float = 60.0) -> None:
        """
        Start outbound call.
        
        Sends INVITE and waits for answer.
        
        Args:
            timeout: Maximum time to wait for answer
            
        Raises:
            CallFailedError: If call fails to connect
            CallRejectedError: If call is rejected
            CallTimeoutError: If no answer within timeout
        """
        if self._direction != CallDirection.OUTBOUND:
            raise CallStateError("start", self._state, "Use answer() for inbound calls")
        
        if self._state != CallState.IDLE:
            raise CallStateError("start", self._state)
        
        self._state = CallState.DIALING
        
        # Start RTP session
        await self._start_rtp()
        
        # Build SDP offer
        sdp_builder = SDPBuilder(local_ip=self._local_ip)
        sdp = sdp_builder.create_offer(audio_port=self._rtp_port)
        self._local_sdp = sdp_builder.serialize(sdp)
        
        # Build INVITE request
        self._invite_request = self._sip_builder.invite(
            from_uri=self._from_uri,
            to_uri=self._to_uri,
            sdp=self._local_sdp,
            call_id=self._call_id,
            from_tag=self._local_tag,
        )
        
        # Send INVITE
        response = await self._send_invite(timeout)
        
        if response is None:
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.TIMEOUT
            raise CallTimeoutError("No response to INVITE")
        
        if response.status_code >= 300:
            # Must send ACK for all final responses (RFC 3261)
            await self._send_ack(response)
            
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.REJECTED
            raise CallRejectedError(response.status_code, response.reason_phrase)
        
        if response.status_code >= 200:
            # Call answered
            self._remote_tag = response.to_tag
            self._answered_at = time.time()
            self._state = CallState.ACTIVE
            
            # Parse remote SDP
            if response.body:
                self._remote_sdp = response.body
                await self._setup_media_from_sdp(response.body)
            
            # Send ACK
            await self._send_ack(response)
            
            logger.info(f"Call {self._call_id} connected")
    
    async def _send_invite(self, timeout: float) -> SIPResponse | None:
        """Send INVITE and handle authentication."""
        if not self._server_address:
            raise CallFailedError(message="No server address")
        
        data = serialize_request(self._invite_request)
        
        # Create response future
        response_future: asyncio.Future = asyncio.get_event_loop().create_future()
        
        def on_response(data: bytes, addr: Address) -> None:
            try:
                parser = SIPParser()
                msg = parser.parse(data)
                if hasattr(msg, 'status_code') and msg.call_id == self._call_id:
                    if msg.status_code == 100:
                        pass  # Ignore TRYING
                    elif msg.status_code == 180 or msg.status_code == 183:
                        self._state = CallState.RINGING
                    elif not response_future.done():
                        response_future.set_result(msg)
            except Exception as e:
                logger.error(f"Error parsing response: {e}")
        
        old_handler = self._transport._on_data_received
        self._transport.on_data_received(on_response)
        
        try:
            await self._transport.send(data, self._server_address)
            
            response = await asyncio.wait_for(response_future, timeout=timeout)
            
            # Handle auth challenge
            if response.status_code in (401, 407):
                if not self._username or not self._password:
                    return response
                
                auth = DigestAuth(self._username, self._password)
                challenge = auth.parse_challenge(response)
                
                auth_header = auth.generate_authorization(
                    method="INVITE",
                    uri=str(self._invite_request.uri),
                    challenge=challenge,
                )
                
                # Rebuild INVITE with auth
                self._cseq += 1
                self._invite_request = self._sip_builder.invite(
                    from_uri=self._from_uri,
                    to_uri=self._to_uri,
                    sdp=self._local_sdp,
                    call_id=self._call_id,
                    from_tag=self._local_tag,
                    cseq=self._cseq,
                    extra_headers={"authorization": auth_header},
                )
                
                # Reset and retry
                response_future = asyncio.get_event_loop().create_future()
                data = serialize_request(self._invite_request)
                await self._transport.send(data, self._server_address)
                
                response = await asyncio.wait_for(response_future, timeout=timeout)
            
            return response
        
        except asyncio.TimeoutError:
            return None
        
        finally:
            self._transport._on_data_received = old_handler
    
    async def answer(self) -> None:
        """
        Answer incoming call.
        
        Raises:
            CallStateError: If not an incoming call or wrong state
        """
        if self._direction != CallDirection.INBOUND:
            raise CallStateError("answer", self._state, "Use start() for outbound calls")
        
        if self._state not in (CallState.IDLE, CallState.RINGING):
            raise CallStateError("answer", self._state)
        
        # Start RTP session
        await self._start_rtp()
        
        # Build SDP answer
        sdp_builder = SDPBuilder(local_ip=self._local_ip)
        
        if self._remote_sdp:
            offer_sdp = SDPParser().parse(self._remote_sdp)
            sdp = sdp_builder.create_answer(offer_sdp, audio_port=self._rtp_port)
        else:
            sdp = sdp_builder.create_offer(audio_port=self._rtp_port)
        
        self._local_sdp = sdp_builder.serialize(sdp)
        
        # Build 200 OK
        response = self._sip_builder.response(
            self._incoming_invite,
            200,
            body=self._local_sdp,
            to_tag=self._local_tag,
        )
        
        # Send response
        if self._remote_address:
            data = serialize_response(response)
            await self._transport.send(data, self._remote_address)
        
        self._answered_at = time.time()
        self._state = CallState.ACTIVE
        
        # Set up media
        if self._remote_sdp:
            await self._setup_media_from_sdp(self._remote_sdp)
        
        logger.info(f"Call {self._call_id} answered")
    
    async def reject(self, code: int = 603, reason: str | None = None) -> None:
        """
        Reject incoming call.
        
        Args:
            code: SIP status code (default: 603 Decline)
            reason: Custom reason phrase
        """
        if self._direction != CallDirection.INBOUND:
            return
        
        if self._incoming_invite and self._remote_address:
            response = self._sip_builder.response(
                self._incoming_invite,
                code,
                reason_phrase=reason,
            )
            data = serialize_response(response)
            await self._transport.send(data, self._remote_address)
        
        self._state = CallState.TERMINATED
        self._hangup_cause = HangupCause.REJECTED
    
    async def hangup(self) -> None:
        """
        Hang up the call.
        
        Sends BYE request.
        """
        if self._state == CallState.TERMINATED:
            return
        
        if self._state == CallState.ACTIVE:
            # Send BYE
            await self._send_bye()
        elif self._state in (CallState.DIALING, CallState.RINGING):
            # Send CANCEL
            await self._send_cancel()
        
        await self._cleanup()
        
        self._state = CallState.TERMINATED
        self._ended_at = time.time()
        
        if self._on_hangup:
            self._on_hangup(self._hangup_cause.value)
        
        logger.info(f"Call {self._call_id} ended: {self._hangup_cause.value}")
    
    async def _send_bye(self) -> None:
        """Send BYE request."""
        if not self._server_address:
            return
        
        self._cseq += 1
        
        request = self._sip_builder.bye(
            dialog_call_id=self._call_id,
            from_uri=self._from_uri,
            to_uri=self._to_uri,
            from_tag=self._local_tag,
            to_tag=self._remote_tag or "",
            cseq=self._cseq,
        )
        
        data = serialize_request(request)
        await self._transport.send(data, self._server_address)
    
    async def _send_cancel(self) -> None:
        """Send CANCEL request."""
        if not self._invite_request or not self._server_address:
            return
        
        request = self._sip_builder.cancel(self._invite_request)
        data = serialize_request(request)
        await self._transport.send(data, self._server_address)
    
    async def _send_ack(self, response: SIPResponse) -> None:
        """Send ACK for 2xx response."""
        if not self._invite_request or not self._server_address:
            return
        
        request = self._sip_builder.ack(
            self._invite_request,
            response,
        )
        data = serialize_request(request)
        await self._transport.send(data, self._server_address)
    
    # === Media Operations ===
    
    async def _start_rtp(self) -> None:
        """Start RTP session."""
        config = RTPConfig(
            local_ip=self._local_ip,
            local_port=self._rtp_port,
            payload_type=self._codec.payload_type,
            clock_rate=self._codec.clock_rate,
        )
        
        self._rtp_session = RTPSession(config)
        await self._rtp_session.start()
        
        # Set up packet handler
        self._rtp_session.on_packet(self._on_rtp_packet)
    
    async def _setup_media_from_sdp(self, sdp_bytes: bytes) -> None:
        """Set up media from remote SDP."""
        sdp = SDPParser().parse(sdp_bytes)
        
        audio = sdp.audio_media
        if audio:
            remote_addr = sdp.get_audio_address()
            if remote_addr and self._rtp_session:
                self._rtp_session.set_remote_address(remote_addr)
            
            # Select codec
            codec_info = sdp.get_audio_codec()
            if codec_info:
                pt, name, rate = codec_info
                if name.upper() == "PCMU":
                    self._codec = PCMUCodec()
                elif name.upper() == "PCMA":
                    self._codec = PCMACodec()
        
        # Create audio player
        if self._rtp_session:
            self._audio_player = AudioPlayer(
                self._rtp_session,
                self._codec,
            )
    
    def _on_rtp_packet(self, data: bytes, addr: Address) -> None:
        """Handle received RTP packet."""
        try:
            packet = RTPPacket.parse_fast(data)
            
            # Check for DTMF
            if packet.payload_type == CodecType.TELEPHONE_EVENT:
                self._handle_dtmf_packet(packet)
        except Exception as e:
            logger.debug(f"Error processing RTP packet: {e}")
    
    def _handle_dtmf_packet(self, packet: RTPPacket) -> None:
        """Handle DTMF RTP packet."""
        from .protocol.rtp import DTMFEvent
        
        try:
            event = DTMFEvent.parse(packet.payload)
            
            if event.end:
                digit = event.digit
                self._dtmf_buffer.append(digit)
                self._dtmf_event.set()
                
                # Invoke callback
                if self._on_dtmf:
                    asyncio.create_task(self._on_dtmf(digit))
        except Exception:
            pass
    
    async def play(self, audio: str | AudioStream) -> PlaybackHandle:
        """
        Play audio file or stream.
        
        Args:
            audio: File path or AudioStream
            
        Returns:
            PlaybackHandle for control
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("play", self._state)
        
        if not self._audio_player:
            raise CallStateError("play", self._state, "Media not set up")
        
        if isinstance(audio, str):
            stream = AudioStream.from_file(audio)
        else:
            stream = audio
        
        return await self._audio_player.play(stream)
    
    async def say(
        self,
        text: str,
        voice: str = "en-US-AriaNeural",
    ) -> PlaybackHandle:
        """
        Play text-to-speech audio.
        
        Args:
            text: Text to speak
            voice: TTS voice name
            
        Returns:
            PlaybackHandle for control
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("say", self._state)
        
        # Generate TTS audio
        from .features.tts import EdgeTTSEngine
        
        engine = EdgeTTSEngine()
        audio = await engine.synthesize(text, voice)
        
        return await self.play(audio)
    
    async def gather(
        self,
        max_digits: int = 1,
        timeout: float = 5.0,
        finish_on_key: str | None = "#",
    ) -> str:
        """
        Collect DTMF digits.
        
        Args:
            max_digits: Maximum digits to collect
            timeout: Timeout in seconds
            finish_on_key: Key to end collection early
            
        Returns:
            Collected digits string
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("gather", self._state)
        
        self._dtmf_buffer.clear()
        self._dtmf_event.clear()
        
        digits = []
        deadline = time.time() + timeout
        
        while len(digits) < max_digits:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            
            try:
                await asyncio.wait_for(
                    self._dtmf_event.wait(),
                    timeout=remaining,
                )
                self._dtmf_event.clear()
                
                while self._dtmf_buffer:
                    digit = self._dtmf_buffer.pop(0)
                    
                    if finish_on_key and digit == finish_on_key:
                        return "".join(digits)
                    
                    digits.append(digit)
                    
                    if len(digits) >= max_digits:
                        break
            
            except asyncio.TimeoutError:
                break
        
        return "".join(digits)
    
    async def send_dtmf(self, digits: str) -> None:
        """
        Send DTMF digits.
        
        Args:
            digits: DTMF digits to send
        """
        if self._state != CallState.ACTIVE or not self._rtp_session:
            raise CallStateError("send_dtmf", self._state)
        
        from .protocol.rtp import DTMFEventStream
        
        stream = DTMFEventStream(payload_type=CodecType.TELEPHONE_EVENT)
        
        for digit in digits:
            packets = stream.generate_digit(digit)
            for payload, is_first in packets:
                self._rtp_session.send(payload, marker=is_first)
                await asyncio.sleep(0.02)  # 20ms between packets
            
            await asyncio.sleep(0.1)  # Gap between digits
    
    async def record(
        self,
        max_duration: float = 60.0,
        silence_timeout: float = 5.0,
    ) -> "Recording":
        """
        Record call audio.
        
        Args:
            max_duration: Maximum recording length in seconds
            silence_timeout: Stop after this much silence
            
        Returns:
            Recording object with audio data
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("record", self._state)
        
        from .features.recording import CallRecorder
        
        recorder = CallRecorder()
        return await recorder.record(
            self,
            max_duration=max_duration,
            silence_timeout=silence_timeout,
        )
    
    async def transfer(self, to: str) -> bool:
        """
        Transfer call to another party.
        
        Args:
            to: Destination SIP URI
            
        Returns:
            True if transfer succeeded
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("transfer", self._state)
        
        # Build REFER request
        self._cseq += 1
        
        refer_to = to if to.startswith("sip:") else f"sip:{to}"
        
        # For now, just hang up - full REFER implementation would be complex
        logger.warning("Call transfer not fully implemented - hanging up")
        await self.hangup()
        return False
    
    async def _cleanup(self) -> None:
        """Clean up call resources."""
        if self._audio_player:
            await self._audio_player.stop_async()
        
        if self._rtp_session:
            await self._rtp_session.stop()
            self._rtp_session = None
    
    # === Internal Handlers ===
    
    async def _handle_request(self, request: SIPRequest, address: Address) -> None:
        """Handle incoming SIP request for this call."""
        method = request.method
        if isinstance(method, SIPMethod):
            method = method.value
        
        if method == "BYE":
            # Remote hangup
            self._state = CallState.TERMINATED
            self._ended_at = time.time()
            self._hangup_cause = HangupCause.NORMAL
            
            # Send 200 OK
            response = self._sip_builder.response(request, 200)
            data = serialize_response(response)
            await self._transport.send(data, address)
            
            await self._cleanup()
            
            if self._on_hangup:
                self._on_hangup(self._hangup_cause.value)
        
        elif method == "ACK":
            # ACK for our 200 OK (inbound call)
            pass
        
        elif method == "CANCEL":
            # Cancelled before answer
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.CANCELLED
            
            # Send 200 OK for CANCEL
            response = self._sip_builder.response(request, 200)
            data = serialize_response(response)
            await self._transport.send(data, address)
            
            await self._cleanup()
            
            if self._on_hangup:
                self._on_hangup(self._hangup_cause.value)
    
    async def _handle_response(self, response: SIPResponse, address: Address) -> None:
        """Handle incoming SIP response for this call."""
        # Handled by transaction/futures in start() method
        pass


