"""
Call Manager

Manages active calls with TaskGroup-based concurrency.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

from ..exceptions import CallNotFoundError, MaxCallsReachedError
from ..types import Address, CallState

if TYPE_CHECKING:
    from ..call import Call
    from ..protocol.sip import SIPRequest, SIPResponse
    from ..transport import UDPTransport

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CallManagerConfig:
    """Call manager configuration."""
    
    max_concurrent_calls: int = 100
    call_timeout: float = 60.0  # Default call setup timeout
    cleanup_interval: float = 30.0  # Interval for cleanup task


class CallManager:
    """
    Manages active SIP calls.
    
    Features:
    - TaskGroup-based call handling
    - Call routing by Call-ID
    - Automatic cleanup of completed calls
    - Max concurrent calls limit
    
    Example:
        manager = CallManager(transport, config)
        await manager.start()
        
        # Create outbound call
        call = await manager.create_call(to_uri="sip:bob@example.com")
        
        # Handle incoming call
        manager.on_incoming_call(handle_call)
        
        await manager.stop()
    """
    
    __slots__ = (
        "_transport",
        "_config",
        "_calls",
        "_incoming_handler",
        "_running",
        "_cleanup_task",
        "_task_group",
        "_local_ip",
        "_local_port",
        "_rtp_port_range",
        "_next_rtp_port",
    )
    
    def __init__(
        self,
        transport: "UDPTransport",
        config: CallManagerConfig | None = None,
        local_ip: str = "0.0.0.0",
        local_port: int = 5060,
        rtp_port_range: tuple[int, int] = (10000, 20000),
    ):
        self._transport = transport
        self._config = config or CallManagerConfig()
        self._calls: dict[str, "Call"] = {}  # call_id -> Call
        self._incoming_handler: Callable[["Call"], Awaitable[None]] | None = None
        self._running = False
        self._cleanup_task: asyncio.Task | None = None
        self._task_group: asyncio.TaskGroup | None = None
        self._local_ip = local_ip
        self._local_port = local_port
        self._rtp_port_range = rtp_port_range
        self._next_rtp_port = rtp_port_range[0]
    
    @property
    def active_calls(self) -> int:
        """Number of active calls."""
        return len(self._calls)
    
    @property
    def calls(self) -> dict[str, "Call"]:
        """All active calls."""
        return dict(self._calls)
    
    def on_incoming_call(
        self,
        handler: Callable[["Call"], Awaitable[None]],
    ) -> None:
        """
        Set handler for incoming calls.
        
        Args:
            handler: Async function to handle new calls
        """
        self._incoming_handler = handler
    
    async def start(self) -> None:
        """Start the call manager."""
        if self._running:
            return
        
        self._running = True
        
        # Set up message handler
        self._transport.on_data_received(self._on_message_received)
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        logger.info("CallManager started")
    
    async def stop(self) -> None:
        """Stop the call manager and terminate all calls."""
        if not self._running:
            return
        
        self._running = False
        
        # Cancel cleanup task
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Terminate all calls
        for call in list(self._calls.values()):
            try:
                await call.hangup()
            except Exception as e:
                logger.error(f"Error terminating call {call.call_id}: {e}")
        
        self._calls.clear()
        
        logger.info("CallManager stopped")
    
    def _allocate_rtp_port(self) -> int:
        """Allocate next RTP port."""
        port = self._next_rtp_port
        self._next_rtp_port += 2  # RTP uses even ports
        
        if self._next_rtp_port >= self._rtp_port_range[1]:
            self._next_rtp_port = self._rtp_port_range[0]
        
        return port
    
    async def create_call(
        self,
        to_uri: str,
        from_uri: str | None = None,
        **kwargs,
    ) -> "Call":
        """
        Create a new outbound call.
        
        Args:
            to_uri: Destination SIP URI
            from_uri: Source SIP URI (optional)
            **kwargs: Additional call parameters
            
        Returns:
            New Call instance
            
        Raises:
            MaxCallsReachedError: If at max concurrent calls
        """
        if len(self._calls) >= self._config.max_concurrent_calls:
            raise MaxCallsReachedError(self._config.max_concurrent_calls)
        
        # Import here to avoid circular import
        from ..call import Call
        
        # Allocate RTP port
        rtp_port = self._allocate_rtp_port()
        
        # Create call
        call = Call(
            transport=self._transport,
            local_ip=self._local_ip,
            local_port=self._local_port,
            rtp_port=rtp_port,
            to_uri=to_uri,
            from_uri=from_uri,
            direction="outbound",
            **kwargs,
        )
        
        # Register call
        self._calls[call.call_id] = call
        
        # Set up cleanup on termination
        call.on_hangup(lambda reason: self._on_call_ended(call))
        
        return call
    
    def get_call(self, call_id: str) -> "Call | None":
        """Get call by Call-ID."""
        return self._calls.get(call_id)
    
    def _on_message_received(self, data: bytes, address: Address) -> None:
        """Handle incoming SIP message."""
        asyncio.create_task(self._handle_message(data, address))
    
    async def _handle_message(self, data: bytes, address: Address) -> None:
        """Process incoming SIP message."""
        from ..protocol.sip import SIPParser, SIPRequest, SIPResponse
        
        try:
            parser = SIPParser()
            message = parser.parse(data)
            
            if isinstance(message, SIPRequest):
                await self._handle_request(message, address)
            else:
                await self._handle_response(message, address)
        
        except Exception as e:
            logger.error(f"Error handling message: {e}")
    
    async def _handle_request(
        self,
        request: "SIPRequest",
        address: Address,
    ) -> None:
        """Handle incoming SIP request."""
        
        call_id = request.call_id
        
        # Check if this belongs to an existing call
        call = self._calls.get(call_id)
        
        if call:
            # Route to existing call
            await call._handle_request(request, address)
        
        elif request.is_invite:
            # New incoming call
            await self._handle_incoming_invite(request, address)
        
        elif request.is_options:
            # Respond to OPTIONS (keep-alive / capability query)
            await self._handle_options(request, address)
        
        else:
            # Unknown request - respond with 481 Call/Transaction Does Not Exist (RFC 3261)
            logger.warning(f"Request for unknown call: {call_id}")
            await self._send_error_response(
                request, 481, address, "Call/Transaction Does Not Exist"
            )
    
    async def _handle_options(
        self,
        request: "SIPRequest",
        address: Address,
    ) -> None:
        """Handle OPTIONS request (keep-alive / capability query)."""
        from ..protocol.sip.builder import serialize_response
        from ..protocol.sip.message import SIPResponse
        
        logger.debug(f"Received OPTIONS from {address}")
        
        # Get To header and add tag if not present
        # Note: All headers are normalized to lowercase by the parser
        to_header = request.headers.get("to", "")
        if ";tag=" not in to_header:
            to_header = f"{to_header};tag={self._generate_tag()}"
        
        from ..protocol.sip.builder import ALLOW_METHODS, SUPPORTED_EXTENSIONS
        
        # Build 200 OK response
        # Using lowercase keys as they get capitalized during serialization
        response = SIPResponse(
            status_code=200,
            reason_phrase="OK",
            headers={
                "via": request.headers.get("via", ""),
                "from": request.headers.get("from", ""),
                "to": to_header,
                "call-id": request.call_id,
                "cseq": request.headers.get("cseq", ""),
                "allow": ALLOW_METHODS,
                "accept": "application/sdp",
                "accept-language": "en",
                "supported": SUPPORTED_EXTENSIONS,
                "user-agent": "PySIP/2.0",
                "content-length": "0",
            },
        )
        
        data = serialize_response(response)
        logger.debug(f"Sending OPTIONS response: {data[:200]}")
        await self._transport.send(data, address)
        logger.info(f"Sent 200 OK for OPTIONS to {address}")
    
    def _generate_tag(self) -> str:
        """Generate random tag."""
        import random
        import string
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    async def _handle_response(
        self,
        response: "SIPResponse",
        address: Address,
    ) -> None:
        """Handle incoming SIP response."""
        call_id = response.call_id
        
        call = self._calls.get(call_id)
        if call:
            await call._handle_response(response, address)
        else:
            logger.warning(f"Response for unknown call: {call_id}")
    
    async def _send_provisional_response(
        self,
        request: "SIPRequest",
        status_code: int,
        address: Address,
        reason_phrase: str | None = None,
    ) -> None:
        """Send a provisional (1xx) response to a request."""
        from ..protocol.sip.builder import serialize_response
        from ..protocol.sip.message import SIPResponse, get_reason_phrase
        
        reason = reason_phrase or get_reason_phrase(status_code)
        
        # Build response with required headers from request
        response = SIPResponse(
            status_code=status_code,
            reason_phrase=reason,
            headers={
                "via": request.headers.get("via", ""),
                "from": request.headers.get("from", ""),
                "to": request.headers.get("to", ""),
                "call-id": request.call_id,
                "cseq": request.headers.get("cseq", ""),
                "user-agent": "PySIP/2.0",
                "content-length": "0",
            },
        )
        
        data = serialize_response(response)
        await self._transport.send(data, address)
        logger.debug(f"Sent {status_code} {reason} to {address}")
    
    async def _send_error_response(
        self,
        request: "SIPRequest",
        status_code: int,
        address: Address,
        reason_phrase: str | None = None,
    ) -> None:
        """Send an error response to a request."""
        from ..protocol.sip.builder import serialize_response
        from ..protocol.sip.message import SIPResponse, get_reason_phrase
        
        reason = reason_phrase or get_reason_phrase(status_code)
        
        # Add to-tag for error responses
        to_header = request.headers.get("to", "")
        if ";tag=" not in to_header.lower():
            to_header = f"{to_header};tag={self._generate_tag()}"
        
        response = SIPResponse(
            status_code=status_code,
            reason_phrase=reason,
            headers={
                "via": request.headers.get("via", ""),
                "from": request.headers.get("from", ""),
                "to": to_header,
                "call-id": request.call_id,
                "cseq": request.headers.get("cseq", ""),
                "user-agent": "PySIP/2.0",
                "content-length": "0",
            },
        )
        
        data = serialize_response(response)
        await self._transport.send(data, address)
        logger.debug(f"Sent {status_code} {reason} to {address}")
    
    async def _handle_incoming_invite(
        self,
        invite: "SIPRequest",
        address: Address,
    ) -> None:
        """Handle new incoming INVITE."""
        # RFC 3261: Send 100 Trying immediately to stop retransmissions
        await self._send_provisional_response(invite, 100, address, "Trying")
        
        if len(self._calls) >= self._config.max_concurrent_calls:
            logger.warning("Max calls reached, rejecting incoming call")
            # Send 503 Service Unavailable per RFC 3261
            await self._send_error_response(invite, 503, address, "Service Unavailable")
            return
        
        # Import here to avoid circular import
        from ..call import Call
        
        # Allocate RTP port
        rtp_port = self._allocate_rtp_port()
        
        # Create call
        call = Call(
            transport=self._transport,
            local_ip=self._local_ip,
            local_port=self._local_port,
            rtp_port=rtp_port,
            direction="inbound",
            incoming_invite=invite,
            remote_address=address,
        )
        
        # Register call
        self._calls[call.call_id] = call
        
        # Set up cleanup on termination
        call.on_hangup(lambda reason: self._on_call_ended(call))
        
        # Invoke handler
        if self._incoming_handler:
            asyncio.create_task(self._incoming_handler(call))
        else:
            # No handler - reject call
            logger.warning("No incoming call handler, rejecting")
            await call.reject(603)
    
    def _on_call_ended(self, call: "Call") -> None:
        """Handle call termination."""
        call_id = call.call_id
        
        if call_id in self._calls:
            del self._calls[call_id]
        
        logger.debug(f"Call {call_id} removed from manager")
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of terminated calls."""
        try:
            while self._running:
                await asyncio.sleep(self._config.cleanup_interval)
                
                # Find terminated calls
                terminated = [
                    call_id for call_id, call in self._calls.items()
                    if call.state == CallState.TERMINATED
                ]
                
                # Remove them
                for call_id in terminated:
                    if call_id in self._calls:
                        del self._calls[call_id]
                
                if terminated:
                    logger.debug(f"Cleaned up {len(terminated)} terminated calls")
        
        except asyncio.CancelledError:
            pass


async def run_with_call_manager(
    transport: "UDPTransport",
    handler: Callable[["Call"], Awaitable[None]],
    config: CallManagerConfig | None = None,
) -> None:
    """
    Run call manager with given handler.
    
    Convenience function for simple use cases.
    
    Args:
        transport: SIP transport
        handler: Incoming call handler
        config: Optional configuration
    """
    manager = CallManager(transport, config)
    manager.on_incoming_call(handler)
    
    try:
        await manager.start()
        # Run until cancelled
        while True:
            await asyncio.sleep(1)
    finally:
        await manager.stop()


