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
    - Async context manager for automatic cleanup
    - Configurable headers, codecs, caller ID before connecting
    
    Example (simple outbound - context manager):
        async with client.dial("sip:bob@example.com") as call:
            await call.say("Hello, this is a test call")
            result = await call.gather(max_digits=4, timeout=10)
            # Auto-hangup when exiting
    
    Example (advanced outbound - configure before connecting):
        call = client.create_call("sip:bob@example.com")
        call.set_caller_id("sip:support@company.com")
        call.set_display_name("Support Line")
        call.add_header("X-Campaign-ID", "promo123")
        call.set_codecs(["pcmu", "pcma"])
        call.on("ringing", lambda: print("Ringing..."))
        
        await call.connect()
        await call.say("Hello!")
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
        "_last_dtmf_timestamp",  # Track last DTMF RTP timestamp for deduplication
        "_on_dtmf",
        "_on_hangup",
        "_on_amd_result",
        "_created_at",
        "_answered_at",
        "_ended_at",
        "_hangup_cause",
        "_remote_address",
        "_incoming_invite",
        # Configuration options (set before connect)
        "_custom_headers",
        "_preferred_codecs",
        "_caller_id",
        "_display_name",
        "_custom_user_agent",
        "_early_media",
        "_connect_timeout",
        "_event_handlers",
        "_pending_tasks",  # Track async event handler tasks for cleanup
        # Session Timer (RFC 4028)
        "_session_expires",
        "_min_se",
        "_session_refresher",
        "_session_timer_task",
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
        self._last_dtmf_timestamp: int | None = None  # For RFC 2833 deduplication
        self._on_dtmf: Callable[[str], Awaitable[None]] | None = None
        
        # Callbacks
        self._on_hangup: Callable[[str], None] | None = None
        self._on_amd_result: Callable[["AMDResult"], Awaitable[None]] | None = None
        
        # Timestamps
        self._created_at = time.time()
        self._answered_at: float | None = None
        self._ended_at: float | None = None
        self._hangup_cause = HangupCause.NORMAL
        
        # Configuration options (set before connect)
        self._custom_headers: dict[str, str] = {}
        self._preferred_codecs: list[str] = []
        self._caller_id: str | None = None
        self._display_name: str | None = None
        self._custom_user_agent: str | None = None
        self._early_media = False
        self._connect_timeout = 60.0
        self._event_handlers: dict[str, list[Callable]] = {
            "ringing": [],
            "answered": [],
            "hangup": [],
            "transfer": [],  # Called when REFER is received with target URI
        }
        self._pending_tasks: set[asyncio.Task] = set()  # Track async handler tasks
        
        # Session Timer (RFC 4028)
        self._session_expires: int = 1800  # Default 30 minutes
        self._min_se: int = 90  # Minimum session interval (90 seconds per RFC)
        self._session_refresher: Literal["uac", "uas"] | None = None
        self._session_timer_task: asyncio.Task | None = None
        
        # Handle incoming INVITE
        if incoming_invite:
            self._call_id = incoming_invite.call_id
            self._remote_tag = incoming_invite.from_tag
            
            # Extract URIs from INVITE - for inbound we swap from/to
            # The From of INVITE becomes our To (remote party)
            # The To of INVITE becomes our From (local party)
            self._from_uri = str(incoming_invite.to_address.uri)
            self._to_uri = str(incoming_invite.from_address.uri)
            
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
    
    # === Async Context Manager ===
    
    async def __aenter__(self) -> "Call":
        """
        Async context manager entry.
        
        Automatically connects outbound calls or answers inbound calls.
        
        Example:
            async with client.dial("sip:bob@example.com") as call:
                await call.say("Hello!")
                # Auto-hangup when exiting context
        """
        if self._direction == CallDirection.OUTBOUND:
            await self.connect()
        else:
            await self.answer()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """
        Async context manager exit.
        
        Automatically hangs up if the call is still active.
        """
        if self._state not in (CallState.TERMINATED, CallState.IDLE):
            try:
                await self.hangup()
            except Exception:
                pass  # Best effort cleanup
        return None
    
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
    
    # === Configuration Methods (call before connect) ===
    
    def add_header(self, name: str, value: str) -> "Call":
        """
        Add a custom SIP header to the INVITE request.
        
        Must be called before connect().
        
        Args:
            name: Header name (e.g., "X-Campaign-ID")
            value: Header value
            
        Returns:
            self for method chaining
            
        Example:
            call.add_header("X-Campaign-ID", "promo123")
            call.add_header("X-Account-ID", "12345")
        """
        self._custom_headers[name.lower()] = value
        return self
    
    def set_codecs(self, codecs: list[str]) -> "Call":
        """
        Set preferred codec order.
        
        Must be called before connect().
        
        Args:
            codecs: List of codec names in preference order
                    (e.g., ["pcmu", "pcma"])
            
        Returns:
            self for method chaining
            
        Example:
            call.set_codecs(["pcmu", "pcma"])
        """
        self._preferred_codecs = [c.lower() for c in codecs]
        return self
    
    def set_caller_id(self, uri: str) -> "Call":
        """
        Override the From URI (caller ID).
        
        Must be called before connect().
        
        Args:
            uri: SIP URI to use as caller ID
            
        Returns:
            self for method chaining
            
        Example:
            call.set_caller_id("sip:+18005551234@domain.com")
        """
        self._caller_id = uri
        return self
    
    def set_display_name(self, name: str) -> "Call":
        """
        Set caller display name.
        
        Must be called before connect().
        
        Args:
            name: Display name shown on recipient's phone
            
        Returns:
            self for method chaining
            
        Example:
            call.set_display_name("Acme Support")
        """
        self._display_name = name
        return self
    
    def set_user_agent(self, user_agent: str) -> "Call":
        """
        Override the User-Agent header for this call.
        
        Must be called before connect().
        
        Args:
            user_agent: User-Agent string
            
        Returns:
            self for method chaining
            
        Example:
            call.set_user_agent("MyApp/1.0")
        """
        self._custom_user_agent = user_agent
        return self
    
    def set_early_media(self, enabled: bool) -> "Call":
        """
        Enable or disable early media (183 Session Progress).
        
        Must be called before connect().
        
        Args:
            enabled: Whether to enable early media
            
        Returns:
            self for method chaining
        """
        self._early_media = enabled
        return self
    
    def set_timeout(self, seconds: float) -> "Call":
        """
        Set connection timeout.
        
        Must be called before connect().
        
        Args:
            seconds: Maximum time to wait for answer
            
        Returns:
            self for method chaining
            
        Example:
            call.set_timeout(30)  # 30 second timeout
        """
        self._connect_timeout = seconds
        return self
    
    def on(self, event: str, handler: Callable) -> "Call":
        """
        Register an event handler.
        
        Supported events:
        - "ringing": Called when remote party is ringing (180/183)
        - "answered": Called when call is answered (200 OK)
        - "hangup": Called when call ends
        
        Must be called before connect() for ringing/answered events.
        
        Args:
            event: Event name
            handler: Callback function (can be sync or async)
            
        Returns:
            self for method chaining
            
        Example:
            call.on("ringing", lambda: print("Ringing..."))
            call.on("answered", lambda: print("Connected!"))
        """
        if event in self._event_handlers:
            self._event_handlers[event].append(handler)
        else:
            logger.warning(f"Unknown event: {event}")
        return self
    
    def set_session_timer(
        self,
        expires: int = 1800,
        min_se: int = 90,
    ) -> "Call":
        """
        Enable Session Timer (RFC 4028).
        
        Session timers automatically refresh the session to prevent it
        from timing out due to NAT bindings or network issues.
        
        Must be called before connect().
        
        Args:
            expires: Session interval in seconds (default 1800 = 30 min)
            min_se: Minimum session expires (default 90 seconds per RFC)
            
        Returns:
            self for method chaining
            
        Example:
            call.set_session_timer(expires=300)  # 5 minute refresh
            await call.connect()
        """
        if self._state != CallState.IDLE:
            logger.warning("set_session_timer() should be called before connect()")
        
        self._session_expires = max(expires, min_se)
        self._min_se = min_se
        return self
    
    async def _start_session_timer(self) -> None:
        """Start the session refresh timer."""
        if self._session_timer_task:
            return
        
        self._session_timer_task = asyncio.create_task(self._session_timer_loop())
    
    async def _stop_session_timer(self) -> None:
        """Stop the session refresh timer."""
        if self._session_timer_task:
            self._session_timer_task.cancel()
            try:
                await self._session_timer_task
            except asyncio.CancelledError:
                pass
            self._session_timer_task = None
    
    async def _session_timer_loop(self) -> None:
        """
        Periodic session refresh loop (RFC 4028).
        
        Sends re-INVITE before session expires to keep it alive.
        Refresh is sent at half the session interval.
        """
        try:
            # Refresh at half the session interval (with some margin)
            refresh_interval = max(self._session_expires // 2 - 5, self._min_se)
            
            while self._state == CallState.ACTIVE:
                await asyncio.sleep(refresh_interval)
                
                if self._state != CallState.ACTIVE:
                    break
                
                # We're the refresher or no refresher specified
                if self._session_refresher in (None, "uac"):
                    logger.debug(f"Session timer: sending refresh re-INVITE for {self._call_id}")
                    try:
                        await self._send_reinvite()
                    except Exception as e:
                        logger.warning(f"Session refresh failed: {e}")
                        # Don't kill the call on refresh failure
                        
        except asyncio.CancelledError:
            pass
    
    def _emit_event(self, event: str) -> None:
        """Emit an event to all registered handlers."""
        handlers = self._event_handlers.get(event, [])
        for handler in handlers:
            try:
                result = handler()
                # If handler is a coroutine, schedule it and track the task
                if asyncio.iscoroutine(result):
                    task = asyncio.create_task(result)
                    self._pending_tasks.add(task)
                    # Remove task from set when done
                    task.add_done_callback(self._pending_tasks.discard)
            except Exception as e:
                logger.error(f"Error in {event} handler: {e}")
    
    # === Call Control ===
    
    async def connect(self, timeout: float | None = None) -> None:
        """
        Connect outbound call.
        
        Sends INVITE and waits for answer. Uses configured timeout or
        the value set via set_timeout().
        
        Args:
            timeout: Maximum time to wait for answer (overrides set_timeout)
            
        Raises:
            CallFailedError: If call fails to connect
            CallRejectedError: If call is rejected
            CallTimeoutError: If no answer within timeout
        """
        if self._direction != CallDirection.OUTBOUND:
            raise CallStateError("connect", self._state, "Use answer() for inbound calls")
        
        if self._state != CallState.IDLE:
            raise CallStateError("connect", self._state)
        
        # Use provided timeout or configured timeout
        actual_timeout = timeout if timeout is not None else self._connect_timeout
        
        self._state = CallState.DIALING
        
        # Start RTP session
        await self._start_rtp()
        
        # Build SDP offer with preferred codecs
        sdp_builder = SDPBuilder(local_ip=self._local_ip)
        sdp = sdp_builder.create_offer(
            audio_port=self._rtp_port,
            codecs=self._preferred_codecs if self._preferred_codecs else None,
        )
        self._local_sdp = sdp_builder.serialize(sdp)
        
        # Determine From URI and display name
        from_uri = self._caller_id if self._caller_id else self._from_uri
        
        # Build extra headers
        extra_headers = dict(self._custom_headers) if self._custom_headers else {}
        
        # Override user agent if set
        if self._custom_user_agent:
            extra_headers["user-agent"] = self._custom_user_agent
        
        # Build INVITE request
        self._invite_request = self._sip_builder.invite(
            from_uri=from_uri,
            to_uri=self._to_uri,
            sdp=self._local_sdp,
            call_id=self._call_id,
            from_tag=self._local_tag,
            from_display_name=self._display_name,
            extra_headers=extra_headers if extra_headers else None,
        )
        
        # Send INVITE
        response = await self._send_invite(actual_timeout)
        
        if response is None:
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.TIMEOUT
            self._emit_event("hangup")
            raise CallTimeoutError("No response to INVITE")
        
        if response.status_code >= 300:
            # Must send ACK for all final responses (RFC 3261)
            await self._send_ack(response)
            
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.REJECTED
            self._emit_event("hangup")
            raise CallRejectedError(response.status_code, response.reason_phrase)
        
        if response.status_code >= 200:
            # Call answered
            self._remote_tag = response.to_tag
            self._answered_at = time.time()
            self._state = CallState.ACTIVE
            
            # Emit answered event
            self._emit_event("answered")
            
            # Start session timer if configured
            if self._session_expires > 0:
                await self._start_session_timer()
            
            # Parse remote SDP
            if response.body:
                self._remote_sdp = response.body
                await self._setup_media_from_sdp(response.body)
            
            # Send ACK
            await self._send_ack(response)
            
            logger.info(f"Call {self._call_id} connected")
    
    # Aliases for backward compatibility
    async def dial(self, timeout: float = 60.0) -> None:
        """
        Dial outbound call (alias for connect()).
        
        .. deprecated::
            Use :meth:`connect` instead.
        """
        return await self.connect(timeout)
    
    async def start(self, timeout: float = 60.0) -> None:
        """
        Start outbound call (alias for connect()).
        
        .. deprecated::
            Use :meth:`connect` instead.
        """
        return await self.connect(timeout)
    
    async def _send_invite(self, timeout: float) -> SIPResponse | None:
        """Send INVITE and handle authentication."""
        if not self._server_address:
            raise CallFailedError(message="No server address")
        
        data = serialize_request(self._invite_request)
        
        # Create response future
        response_future: asyncio.Future = asyncio.get_running_loop().create_future()
        
        def on_response(data: bytes, addr: Address) -> None:
            try:
                parser = SIPParser()
                msg = parser.parse(data)
                if hasattr(msg, 'status_code') and msg.call_id == self._call_id:
                    if msg.status_code == 100:
                        pass  # Ignore TRYING
                    elif msg.status_code == 180 or msg.status_code == 183:
                        self._state = CallState.RINGING
                        self._emit_event("ringing")
                        # Handle early media on 183
                        if msg.status_code == 183 and self._early_media and msg.body:
                            self._remote_sdp = msg.body
                    elif not response_future.done():
                        response_future.set_result(msg)
            except Exception as e:
                logger.error(f"Error parsing response: {e}")
        
        old_handler = self._transport.get_data_handler()
        self._transport.set_data_handler(on_response)
        
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
                
                # Rebuild INVITE with auth (preserve custom headers)
                self._cseq += 1
                from_uri = self._caller_id if self._caller_id else self._from_uri
                retry_headers = dict(self._custom_headers) if self._custom_headers else {}
                retry_headers["authorization"] = auth_header
                if self._custom_user_agent:
                    retry_headers["user-agent"] = self._custom_user_agent
                
                self._invite_request = self._sip_builder.invite(
                    from_uri=from_uri,
                    to_uri=self._to_uri,
                    sdp=self._local_sdp,
                    call_id=self._call_id,
                    from_tag=self._local_tag,
                    cseq=self._cseq,
                    from_display_name=self._display_name,
                    extra_headers=retry_headers,
                )
                
                # Reset and retry
                response_future = asyncio.get_running_loop().create_future()
                data = serialize_request(self._invite_request)
                await self._transport.send(data, self._server_address)
                
                response = await asyncio.wait_for(response_future, timeout=timeout)
            
            return response
        
        except asyncio.TimeoutError:
            return None
        
        finally:
            self._transport.set_data_handler(old_handler)
    
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
        
        # Start session timer if configured (for inbound calls, we're UAS)
        if self._session_expires > 0:
            self._session_refresher = "uas"
            await self._start_session_timer()
        
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
        
        # Emit hangup event
        self._emit_event("hangup")
        
        if self._on_hangup:
            self._on_hangup(self._hangup_cause.value)
        
        logger.info(f"Call {self._call_id} ended: {self._hangup_cause.value}")
    
    async def _send_bye(self) -> None:
        """Send BYE request."""
        # Use appropriate address based on call direction
        target_address = self._server_address or self._remote_address
        if not target_address:
            logger.warning(f"Cannot send BYE: no target address for call {self._call_id}")
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
        await self._transport.send(data, target_address)
        logger.debug(f"Sent BYE to {target_address}")
    
    async def _send_cancel(self) -> None:
        """Send CANCEL request."""
        target_address = self._server_address or self._remote_address
        if not self._invite_request or not target_address:
            return
        
        request = self._sip_builder.cancel(self._invite_request)
        data = serialize_request(request)
        await self._transport.send(data, target_address)
    
    async def _send_ack(self, response: SIPResponse) -> None:
        """Send ACK for 2xx response."""
        target_address = self._server_address or self._remote_address
        if not self._invite_request or not target_address:
            return
        
        request = self._sip_builder.ack(
            self._invite_request,
            response,
        )
        data = serialize_request(request)
        await self._transport.send(data, target_address)
    
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
            
            # RFC 2833: End packets are sent 3 times for redundancy
            # Deduplicate using RTP timestamp - same timestamp = same event
            if event.end:
                if self._last_dtmf_timestamp == packet.timestamp:
                    # Duplicate end packet, ignore
                    return
                
                self._last_dtmf_timestamp = packet.timestamp
                digit = event.digit
                self._dtmf_buffer.append(digit)
                self._dtmf_event.set()
                
                logger.debug(f"DTMF detected: {digit} (ts={packet.timestamp})")
                
                # Invoke callback
                if self._on_dtmf:
                    asyncio.create_task(self._on_dtmf(digit))
        except Exception:
            pass
    
    async def play(
        self,
        audio: str | AudioStream,
        wait: bool = True,
    ) -> PlaybackHandle:
        """
        Play audio file or stream.
        
        Args:
            audio: File path or AudioStream
            wait: If True (default), wait for playback to complete
            
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
        
        handle = await self._audio_player.play(stream)
        
        if wait:
            await handle.wait()
        
        return handle
    
    async def say(
        self,
        text: str,
        voice: str = "en-US-AriaNeural",
        wait: bool = True,
    ) -> PlaybackHandle:
        """
        Play text-to-speech audio.
        
        Args:
            text: Text to speak
            voice: TTS voice name
            wait: If True (default), wait for playback to complete
            
        Returns:
            PlaybackHandle for control
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("say", self._state)
        
        # Generate TTS audio
        from .features.tts import EdgeTTSEngine
        
        engine = EdgeTTSEngine()
        audio = await engine.synthesize(text, voice)
        
        handle = await self.play(audio, wait=False)
        
        if wait:
            await handle.wait()
        
        return handle
    
    async def gather(
        self,
        max_digits: int = 1,
        timeout: float = 5.0,
        finish_on_key: str | None = "#",
    ) -> GatherResult:
        """
        Collect DTMF digits.
        
        Args:
            max_digits: Maximum digits to collect
            timeout: Timeout in seconds
            finish_on_key: Key to end collection early
            
        Returns:
            GatherResult with collected digits and termination reason
            
        Example:
            result = await call.gather(max_digits=4, timeout=10)
            if result.terminated_by == "max_digits":
                print(f"Got PIN: {result.digits}")
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("gather", self._state)
        
        # Check for hangup
        if self._state == CallState.TERMINATED:
            return GatherResult(digits="", terminated_by="hangup")
        
        self._dtmf_buffer.clear()
        self._dtmf_event.clear()
        
        digits: list[str] = []
        deadline = time.time() + timeout
        terminated_by: Literal["max_digits", "timeout", "finish_key", "hangup"] = "timeout"
        
        while len(digits) < max_digits:
            # Check for hangup
            if self._state == CallState.TERMINATED:
                terminated_by = "hangup"
                break
            
            remaining = deadline - time.time()
            if remaining <= 0:
                terminated_by = "timeout"
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
                        return GatherResult(digits="".join(digits), terminated_by="finish_key")
                    
                    digits.append(digit)
                    
                    if len(digits) >= max_digits:
                        terminated_by = "max_digits"
                        break
            
            except asyncio.TimeoutError:
                terminated_by = "timeout"
                break
        
        return GatherResult(digits="".join(digits), terminated_by=terminated_by)
    
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
    
    async def hold(self) -> None:
        """
        Put the call on hold.
        
        Sends a re-INVITE with SDP direction set to sendonly.
        The remote party will hear silence/hold music.
        
        Raises:
            CallStateError: If call is not active
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("hold", self._state)
        
        # Build SDP with sendonly direction
        from .types import MediaDirection
        
        sdp_builder = SDPBuilder(local_ip=self._local_ip)
        sdp = sdp_builder.create_offer(
            audio_port=self._rtp_port,
            direction=MediaDirection.SENDONLY,
        )
        sdp_bytes = sdp_builder.serialize(sdp)
        
        # Send re-INVITE
        await self._send_reinvite(sdp_bytes)
        
        self._state = CallState.HOLDING
        logger.info(f"Call {self._call_id} put on hold")
    
    async def unhold(self) -> None:
        """
        Take the call off hold.
        
        Sends a re-INVITE with SDP direction set to sendrecv.
        
        Raises:
            CallStateError: If call is not on hold
        """
        if self._state not in (CallState.HOLDING, CallState.HELD, CallState.ACTIVE):
            raise CallStateError("unhold", self._state)
        
        # Build SDP with sendrecv direction
        from .types import MediaDirection
        
        sdp_builder = SDPBuilder(local_ip=self._local_ip)
        sdp = sdp_builder.create_offer(
            audio_port=self._rtp_port,
            direction=MediaDirection.SENDRECV,
        )
        sdp_bytes = sdp_builder.serialize(sdp)
        
        # Send re-INVITE
        await self._send_reinvite(sdp_bytes)
        
        self._state = CallState.ACTIVE
        logger.info(f"Call {self._call_id} taken off hold")
    
    async def transfer(self, target_uri: str, attended: bool = False) -> None:
        """
        Transfer call to another party (RFC 3515 REFER).
        
        Performs a blind transfer by default, sending a REFER request
        to the remote party instructing them to call the target.
        
        Args:
            target_uri: SIP URI to transfer the call to (e.g., "sip:alice@example.com")
            attended: If True, perform attended transfer (requires establishing
                     a consultative call first - not yet implemented)
        
        Raises:
            CallStateError: If call is not active
            NotImplementedError: If attended transfer is requested
            
        Example:
            # Blind transfer
            await call.transfer("sip:operator@example.com")
            
            # With phone number
            await call.transfer(f"sip:+15551234567@{server}")
        """
        if self._state != CallState.ACTIVE:
            raise CallStateError("transfer", self._state)
        
        if attended:
            raise NotImplementedError("Attended transfer not yet implemented")
        
        await self._send_refer(target_uri)
        logger.info(f"Call {self._call_id} transfer initiated to {target_uri}")
    
    async def _send_refer(self, target_uri: str) -> None:
        """
        Send REFER request (RFC 3515).
        
        Args:
            target_uri: URI to refer the remote party to
        """
        from .protocol.sip.builder import serialize_request
        from .protocol.sip.message import SIPRequest
        
        target_address = self._server_address or self._remote_address
        if not target_address:
            raise CallFailedError(message="No target address for REFER")
        
        if not self._to_uri or not self._from_uri:
            raise CallFailedError(message="Missing URI for REFER")
        
        self._cseq += 1
        
        # Build REFER request
        # Request-URI is the remote party's URI
        to_uri_parsed = SIPUri.parse(self._to_uri) if isinstance(self._to_uri, str) else self._to_uri
        
        request = SIPRequest(
            method=SIPMethod.REFER,
            uri=to_uri_parsed,
            headers={
                "via": self._sip_builder._via(),
                "from": f"<{self._from_uri}>;tag={self._local_tag}",
                "to": f"<{self._to_uri}>" + (f";tag={self._remote_tag}" if self._remote_tag else ""),
                "call-id": self._call_id,
                "cseq": f"{self._cseq} REFER",
                "contact": f"<sip:{self._sip_builder._username or 'pysip'}@{self._local_ip}:{self._local_port}>",
                "max-forwards": "70",
                "refer-to": f"<{target_uri}>",
                "referred-by": f"<{self._from_uri}>",
                "user-agent": self._custom_user_agent or self._user_agent or "PySIP/2.0",
                "content-length": "0",
            },
        )
        
        data = serialize_request(request)
        await self._transport.send(data, target_address)
        logger.debug(f"Sent REFER to {target_address} for transfer to {target_uri}")
    
    async def _send_reinvite(self, sdp: bytes) -> None:
        """Send a re-INVITE with new SDP."""
        target_address = self._server_address or self._remote_address
        if not target_address:
            raise CallFailedError(message="No target address for re-INVITE")
        
        self._cseq += 1
        
        request = self._sip_builder.invite(
            from_uri=self._from_uri,
            to_uri=self._to_uri,
            sdp=sdp,
            call_id=self._call_id,
            from_tag=self._local_tag,
            to_tag=self._remote_tag,
            cseq=self._cseq,
        )
        
        data = serialize_request(request)
        await self._transport.send(data, target_address)
        
        # Note: A full implementation would wait for response and handle ACK
        # For simplicity, we send and continue - most servers accept this
    
    def mute(self) -> None:
        """
        Mute outgoing audio.
        
        Stops sending RTP packets while still receiving.
        """
        if self._audio_player:
            self._audio_player.stop()
        logger.debug(f"Call {self._call_id} muted")
    
    def unmute(self) -> None:
        """
        Unmute outgoing audio.
        
        Resumes sending RTP packets.
        """
        # Audio will resume when play() or say() is called
        logger.debug(f"Call {self._call_id} unmuted")
    
    async def _cleanup(self) -> None:
        """Clean up call resources."""
        # Cancel any pending async event handler tasks
        for task in list(self._pending_tasks):
            if not task.done():
                task.cancel()
        self._pending_tasks.clear()
        
        # Stop session timer
        await self._stop_session_timer()
        
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
            # Cancelled before answer - RFC 3261 Section 9.2
            self._state = CallState.TERMINATED
            self._hangup_cause = HangupCause.CANCELLED
            
            # Send 200 OK for CANCEL
            response = self._sip_builder.response(request, 200)
            data = serialize_response(response)
            await self._transport.send(data, address)
            
            # RFC 3261: Must also send 487 Request Terminated for the original INVITE
            if self._incoming_invite:
                response_487 = self._sip_builder.response(
                    self._incoming_invite,
                    487,
                    reason_phrase="Request Terminated",
                    to_tag=self._local_tag,
                )
                data_487 = serialize_response(response_487)
                await self._transport.send(data_487, address)
                logger.debug(f"Sent 487 Request Terminated for INVITE after CANCEL")
            
            await self._cleanup()
            
            if self._on_hangup:
                self._on_hangup(self._hangup_cause.value)
        
        elif method == "REFER":
            # Handle incoming transfer request (RFC 3515)
            await self._handle_refer(request, address)
    
    async def _handle_refer(self, request: SIPRequest, address: Address) -> None:
        """
        Handle incoming REFER request (RFC 3515).
        
        For now, we accept the REFER but don't automatically perform the transfer.
        Applications should handle the on_transfer callback to decide what to do.
        """
        refer_to = request.headers.get("refer-to", "")
        
        # Extract target URI from Refer-To header
        target_uri = refer_to.strip("<>").split(">")[0]
        
        logger.info(f"Received REFER to {target_uri}")
        
        # Send 202 Accepted - we'll process it
        response = self._sip_builder.response(request, 202, reason_phrase="Accepted")
        data = serialize_response(response)
        await self._transport.send(data, address)
        
        # Store transfer target for application to handle
        # Applications can use call.on("transfer", handler) to handle this
        if "transfer" in self._event_handlers and self._event_handlers["transfer"]:
            for handler in self._event_handlers["transfer"]:
                try:
                    result = handler(target_uri)
                    if asyncio.iscoroutine(result):
                        task = asyncio.create_task(result)
                        self._pending_tasks.add(task)
                        task.add_done_callback(self._pending_tasks.discard)
                except Exception as e:
                    logger.error(f"Error in transfer handler: {e}")
        else:
            # No handler registered - log warning
            logger.warning(f"Received REFER to {target_uri} but no transfer handler registered")
    
    async def _handle_response(self, response: SIPResponse, address: Address) -> None:
        """Handle incoming SIP response for this call."""
        # Handled by transaction/futures in start() method
        pass


