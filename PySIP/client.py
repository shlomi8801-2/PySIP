"""
SIPClient - Main Entry Point

High-level async SIP client for making and receiving calls.
"""

from __future__ import annotations

import asyncio
import logging
import socket
from typing import TYPE_CHECKING, Awaitable, Callable, Literal

from .exceptions import (
    AuthenticationFailed,
    RegistrationError,
    TransportError,
)
from .protocol.sip import DigestAuth, SIPBuilder, SIPParser
from .protocol.sip.builder import serialize_request, serialize_response
from .session.manager import CallManager, CallManagerConfig
from .transport import UDPTransport
from .types import (
    Address,
    ClientConfig,
    SIPMethod,
    SIPStatusCode,
    TransportType,
)

if TYPE_CHECKING:
    from .call import Call
    from .protocol.sip import SIPRequest, SIPResponse

logger = logging.getLogger(__name__)


class SIPClient:
    """
    Async SIP client for VoIP applications.
    
    Features:
    - Async context manager for clean resource management
    - Automatic registration and re-registration
    - Incoming and outgoing call handling
    - High-performance async I/O
    
    Example:
        async with SIPClient(
            username="alice",
            password="secret",
            server="sip.example.com",
        ) as client:
            # Register with server
            await client.register()
            
            # Simple: One-step dial (returns connected call)
            call = await client.dial("sip:bob@example.com")
            await call.say("Hello!")
            await call.hangup()
            
            # Or use context manager (recommended)
            async with client.dial("sip:bob@example.com") as call:
                await call.say("Hello!")
                # Auto-hangup when exiting
            
            # Advanced: Configure call before connecting
            call = client.create_call("sip:bob@example.com")
            call.set_caller_id("sip:support@company.com")
            call.add_header("X-Campaign-ID", "promo123")
            await call.connect()
            await call.say("Hello!")
            
            # Or handle incoming calls
            @client.on_incoming_call
            async def handle_call(call):
                await call.answer()
                await call.say("Hello, how can I help you?")
    
    Configuration:
        - username: SIP account username
        - password: SIP account password
        - server: SIP server hostname or IP
        - port: SIP server port (default: 5060)
        - transport: UDP, TCP, or TLS (default: UDP)
        - max_concurrent_calls: Maximum simultaneous calls (default: 100)
        - rtp_port_range: Port range for RTP media (default: 10000-20000)
    """
    
    __slots__ = (
        "_config",
        "_transport",
        "_call_manager",
        "_sip_builder",
        "_digest_auth",
        "_registered",
        "_registration_task",
        "_local_ip",
        "_running",
        "_incoming_handler",
    )
    
    def __init__(
        self,
        username: str,
        password: str,
        server: str,
        *,
        port: int = 5060,
        transport: Literal["UDP", "TCP", "TLS"] = "UDP",
        local_ip: str | None = None,
        local_port: int = 0,
        user_agent: str = "PySIP/2.0",
        register_expires: int = 300,
        max_concurrent_calls: int = 100,
        rtp_port_range: tuple[int, int] = (10000, 20000),
    ):
        """
        Initialize SIP client.
        
        Args:
            username: SIP account username
            password: SIP account password
            server: SIP server hostname or IP
            port: SIP server port
            transport: Transport protocol (UDP/TCP/TLS)
            local_ip: Local IP address (auto-detect if None)
            local_port: Local SIP port (0 for auto-assign)
            user_agent: User-Agent header value
            register_expires: Registration expiry in seconds
            max_concurrent_calls: Maximum concurrent calls
            rtp_port_range: RTP port range tuple (start, end)
        """
        self._config = ClientConfig(
            username=username,
            password=password,
            server=server,
            port=port,
            transport=TransportType(transport),
            local_ip=local_ip,
            local_port=local_port,
            user_agent=user_agent,
            register_expires=register_expires,
            max_concurrent_calls=max_concurrent_calls,
            rtp_port_range=rtp_port_range,
        )
        
        self._transport: UDPTransport | None = None
        self._call_manager: CallManager | None = None
        self._sip_builder: SIPBuilder | None = None
        self._digest_auth: DigestAuth | None = None
        self._registered = False
        self._registration_task: asyncio.Task | None = None
        self._local_ip: str | None = local_ip
        self._running = False
        self._incoming_handler: Callable[["Call"], Awaitable[None]] | None = None
    
    @property
    def is_registered(self) -> bool:
        """Check if registered with server."""
        return self._registered
    
    @property
    def is_running(self) -> bool:
        """Check if client is running."""
        return self._running
    
    @property
    def active_calls(self) -> int:
        """Number of active calls."""
        if self._call_manager:
            return self._call_manager.active_calls
        return 0
    
    @property
    def local_uri(self) -> str:
        """Local SIP URI."""
        # Use server domain, not local IP - this is what the registrar expects
        return f"sip:{self._config.username}@{self._config.server}"
    
    async def __aenter__(self) -> "SIPClient":
        """Async context manager entry."""
        await self.start()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self.stop()
    
    async def start(self) -> None:
        """
        Start the SIP client.
        
        Initializes transport and call manager.
        Does NOT register automatically - call register() separately.
        """
        if self._running:
            return
        
        # Auto-detect local IP if not specified
        if not self._local_ip:
            self._local_ip = self._detect_local_ip()
        
        # Create transport
        self._transport = UDPTransport()
        
        # Bind to local address
        local_addr = (self._local_ip, self._config.local_port)
        await self._transport.bind(local_addr)
        
        # Update local port from actual bound port
        if self._transport.local_address:
            self._config.local_port = self._transport.local_address[1]
        
        # Create SIP builder
        self._sip_builder = SIPBuilder(
            local_ip=self._local_ip,
            local_port=self._config.local_port,
            user_agent=self._config.user_agent,
        )
        
        # Create digest auth
        self._digest_auth = DigestAuth(
            self._config.username,
            self._config.password,
        )
        
        # Create call manager
        self._call_manager = CallManager(
            transport=self._transport,
            config=CallManagerConfig(
                max_concurrent_calls=self._config.max_concurrent_calls,
            ),
            local_ip=self._local_ip,
            local_port=self._config.local_port,
            rtp_port_range=self._config.rtp_port_range,
        )
        
        # Set incoming call handler
        if self._incoming_handler:
            self._call_manager.on_incoming_call(self._incoming_handler)
        
        # Start call manager
        await self._call_manager.start()
        
        self._running = True
        logger.info(f"SIPClient started on {self._local_ip}:{self._config.local_port}")
    
    async def stop(self) -> None:
        """
        Stop the SIP client.
        
        Unregisters and closes all connections.
        """
        if not self._running:
            return
        
        self._running = False
        
        # Stop registration task
        if self._registration_task:
            self._registration_task.cancel()
            try:
                await self._registration_task
            except asyncio.CancelledError:
                pass
            self._registration_task = None
        
        # Unregister
        if self._registered:
            try:
                await self.unregister()
            except Exception as e:
                logger.warning(f"Unregister failed: {e}")
        
        # Stop call manager
        if self._call_manager:
            await self._call_manager.stop()
            self._call_manager = None
        
        # Close transport
        if self._transport:
            await self._transport.close()
            self._transport = None
        
        logger.info("SIPClient stopped")
    
    def _detect_local_ip(self) -> str:
        """Detect local IP address that can reach the server."""
        try:
            # Create a UDP socket and "connect" to server
            # This doesn't send data, just determines route
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.connect((self._config.server, self._config.port))
            local_ip = sock.getsockname()[0]
            sock.close()
            return local_ip
        except Exception:
            return "0.0.0.0"
    
    async def register(self) -> None:
        """
        Register with SIP server.
        
        Starts automatic re-registration.
        
        Raises:
            RegistrationError: If registration fails
        """
        if not self._running:
            raise RuntimeError("Client not started")
        
        await self._do_register()
        
        # Start re-registration task
        self._registration_task = asyncio.create_task(
            self._registration_loop()
        )
    
    async def unregister(self) -> None:
        """Unregister from SIP server."""
        if not self._registered:
            return
        
        await self._do_register(expires=0)
        self._registered = False
    
    async def _do_register(self, expires: int | None = None) -> None:
        """Perform REGISTER request."""
        if expires is None:
            expires = self._config.register_expires
        
        server_uri = f"sip:{self._config.server}"
        from_uri = f"sip:{self._config.username}@{self._config.server}"
        
        # Build REGISTER request
        request = self._sip_builder.register(
            server_uri=server_uri,
            from_uri=from_uri,
            expires=expires,
        )
        
        # Send and get response
        response = await self._send_request(request)
        
        if response is None:
            raise RegistrationError(message="No response from server")
        
        if response.status_code == 401 or response.status_code == 407:
            # Authentication required
            challenge = DigestAuth.parse_challenge(response)
            
            method = request.method.value if hasattr(request.method, 'value') else str(request.method)
            auth_header = self._digest_auth.generate_authorization(
                method=method,
                uri=str(request.uri),
                challenge=challenge,
            )
            
            # Rebuild request with auth
            request = self._sip_builder.register(
                server_uri=server_uri,
                from_uri=from_uri,
                expires=expires,
                extra_headers={"authorization": auth_header},
            )
            
            # Send authenticated request
            response = await self._send_request(request)
            
            if response is None:
                raise RegistrationError(message="No response to authenticated request")
        
        if response.status_code == 200:
            self._registered = (expires > 0)
            logger.info(f"{'Registered' if self._registered else 'Unregistered'} with {self._config.server}")
        else:
            raise RegistrationError(
                status_code=response.status_code,
                reason=response.reason_phrase,
            )
    
    async def _registration_loop(self) -> None:
        """Periodic re-registration."""
        # Re-register at 80% of expiry time
        interval = self._config.register_expires * 0.8
        
        try:
            while self._running and self._registered:
                await asyncio.sleep(interval)
                
                if self._running and self._registered:
                    try:
                        await self._do_register()
                    except Exception as e:
                        logger.error(f"Re-registration failed: {e}")
        
        except asyncio.CancelledError:
            pass
    
    async def _send_request(
        self,
        request: "SIPRequest",
        timeout: float = 5.0,
    ) -> "SIPResponse | None":
        """Send SIP request and wait for response."""
        if not self._transport:
            raise RuntimeError("Transport not initialized")
        
        server_addr = (self._config.server, self._config.port)
        data = serialize_request(request)
        request_call_id = request.call_id
        
        # Create response future
        response_future: asyncio.Future = asyncio.get_running_loop().create_future()
        
        # Store the old handler using public method
        old_handler = self._transport.get_data_handler()
        
        def on_response(data: bytes, addr: Address) -> None:
            try:
                parser = SIPParser()
                msg = parser.parse(data)
                if hasattr(msg, 'status_code'):
                    # Match by Call-ID
                    if msg.call_id == request_call_id:
                        if not response_future.done():
                            response_future.set_result(msg)
                    else:
                        # Not for us, pass to old handler
                        if old_handler:
                            old_handler(data, addr)
                else:
                    # It's a request, pass to old handler
                    if old_handler:
                        old_handler(data, addr)
            except Exception as e:
                logger.error(f"Error parsing response: {e}")
                # Pass to old handler on error
                if old_handler:
                    old_handler(data, addr)
        
        # Set our response handler
        self._transport.set_data_handler(on_response)
        
        try:
            await self._transport.send(data, server_addr)
            
            response = await asyncio.wait_for(response_future, timeout=timeout)
            return response
        
        except asyncio.TimeoutError:
            logger.warning(f"Request timed out: {request.method}")
            return None
        
        finally:
            # Restore old handler using public method
            self._transport.set_data_handler(old_handler)
    
    def dial(self, to: str, timeout: float = 60.0, **kwargs) -> "Call":
        """
        Create and connect outbound call.
        
        This method returns a Call object that can be used in two ways:
        
        1. As an async context manager (recommended):
           The call is automatically connected on entry and hung up on exit.
           
        2. Awaited directly:
           Returns a connected Call after dialing completes.
        
        For advanced configuration before connecting, use create_call() instead.
        
        Args:
            to: Destination SIP URI or extension
            timeout: Maximum time to wait for answer (default: 60s)
            **kwargs: Additional call parameters
            
        Returns:
            Call instance that can be awaited or used as context manager
            
        Example:
            # Using context manager (recommended)
            async with client.dial("sip:bob@example.com") as call:
                await call.say("Hello!")
                # Auto-hangup when exiting
            
            # Direct await
            call = await client.dial("sip:bob@example.com")
            await call.say("Hello!")
            await call.hangup()
        """
        call = self.create_call(to, **kwargs)
        call.set_timeout(timeout)
        return call
    
    def create_call(self, to: str, **kwargs) -> "Call":
        """
        Create an unconfigured outbound call.
        
        Use this for advanced scenarios where you need to configure the call
        before connecting (add custom headers, set codecs, etc.).
        
        For simple calls, use dial() instead which handles connection automatically.
        
        Args:
            to: Destination SIP URI or extension
            **kwargs: Additional call parameters
            
        Returns:
            Unconfigured Call instance - call connect() to start
            
        Example:
            call = client.create_call("sip:bob@example.com")
            
            # Configure before connecting
            call.set_caller_id("sip:support@company.com")
            call.set_display_name("Support Line")
            call.add_header("X-Campaign-ID", "promo123")
            call.set_codecs(["pcmu", "pcma"])
            call.on("ringing", lambda: print("Ringing..."))
            
            # Now connect
            await call.connect()
            await call.say("Hello!")
            await call.hangup()
        """
        if not self._call_manager:
            raise RuntimeError("Client not started")
        
        # Import here to avoid circular import
        from .call import Call
        
        # Ensure URI has sip: prefix and domain
        if not to.startswith("sip:") and not to.startswith("sips:"):
            # If no @ symbol, it's just an extension - add server domain
            if "@" not in to:
                to = f"sip:{to}@{self._config.server}"
            else:
                to = f"sip:{to}"
        elif "@" not in to:
            # Has sip: but no domain - add server domain
            to = f"{to}@{self._config.server}"
        
        # Create call via manager
        call = Call(
            transport=self._transport,
            local_ip=self._local_ip,
            local_port=self._config.local_port,
            rtp_port=self._call_manager._allocate_rtp_port(),
            to_uri=to,
            from_uri=self.local_uri,
            direction="outbound",
            server_address=(self._config.server, self._config.port),
            username=self._config.username,
            password=self._config.password,
            user_agent=self._config.user_agent,
        )
        
        # Register with manager
        self._call_manager._calls[call.call_id] = call
        self._call_manager._calls_by_call_id[call.call_id] = call
        
        return call
    
    # Alias for backward compatibility
    def make_call(self, to: str, **kwargs) -> "Call":
        """
        Create outbound call (alias for create_call()).
        
        .. deprecated::
            Use :meth:`dial` or :meth:`create_call` instead.
        """
        return self.create_call(to, **kwargs)
    
    def on_incoming_call(
        self,
        handler: Callable[["Call"], Awaitable[None]],
    ) -> Callable[["Call"], Awaitable[None]]:
        """
        Decorator/method to set incoming call handler.
        
        Can be used as decorator:
            @client.on_incoming_call
            async def handle_call(call):
                await call.answer()
        
        Or directly:
            client.on_incoming_call(handle_call)
        """
        self._incoming_handler = handler
        
        if self._call_manager:
            self._call_manager.on_incoming_call(handler)
        
        return handler


# Convenience function for simple use cases
async def create_client(
    username: str,
    password: str,
    server: str,
    **kwargs,
) -> SIPClient:
    """
    Create and start a SIP client.
    
    Convenience function for simple use cases.
    Remember to call stop() when done.
    
    Example:
        client = await create_client("alice", "secret", "sip.example.com")
        try:
            await client.register()
            # ... use client ...
        finally:
            await client.stop()
    """
    client = SIPClient(username, password, server, **kwargs)
    await client.start()
    return client


