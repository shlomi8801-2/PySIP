"""
Transport Layer Base Classes

Abstract base classes for SIP and RTP transports.
"""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, Callable, Protocol, runtime_checkable

from ..types import Address, TransportState, TransportType

if TYPE_CHECKING:
    from ..protocol.sip import SIPMessage


@runtime_checkable
class TransportProtocol(Protocol):
    """Protocol interface for transport implementations."""
    
    @property
    def state(self) -> TransportState: ...
    
    @property
    def local_address(self) -> Address | None: ...
    
    @property
    def remote_address(self) -> Address | None: ...
    
    async def connect(self, address: Address) -> None: ...
    
    async def send(self, data: bytes, address: Address | None = None) -> None: ...
    
    async def close(self) -> None: ...


class Transport(ABC):
    """
    Abstract base class for transport implementations.
    
    Provides common functionality for UDP, TCP, and TLS transports.
    """
    
    __slots__ = (
        "_state",
        "_local_address",
        "_remote_address",
        "_transport_type",
        "_on_data_received",
        "_on_state_changed",
        "_on_error",
        "_loop",
    )
    
    def __init__(
        self,
        transport_type: TransportType,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._state = TransportState.DISCONNECTED
        self._local_address: Address | None = None
        self._remote_address: Address | None = None
        self._transport_type = transport_type
        self._on_data_received: Callable[[bytes, Address], None] | None = None
        self._on_state_changed: Callable[[TransportState], None] | None = None
        self._on_error: Callable[[Exception], None] | None = None
        self._loop = loop or asyncio.get_event_loop()
    
    @property
    def state(self) -> TransportState:
        """Current transport state."""
        return self._state
    
    @property
    def local_address(self) -> Address | None:
        """Local address (IP, port) if bound."""
        return self._local_address
    
    @property
    def remote_address(self) -> Address | None:
        """Remote address (IP, port) if connected."""
        return self._remote_address
    
    @property
    def transport_type(self) -> TransportType:
        """Transport protocol type."""
        return self._transport_type
    
    @property
    def is_connected(self) -> bool:
        """Check if transport is connected."""
        return self._state == TransportState.CONNECTED
    
    def on_data_received(self, callback: Callable[[bytes, Address], None]) -> None:
        """Set callback for received data."""
        self._on_data_received = callback
    
    def on_state_changed(self, callback: Callable[[TransportState], None]) -> None:
        """Set callback for state changes."""
        self._on_state_changed = callback
    
    def on_error(self, callback: Callable[[Exception], None]) -> None:
        """Set callback for errors."""
        self._on_error = callback
    
    def _set_state(self, state: TransportState) -> None:
        """Update state and notify callback."""
        if self._state != state:
            self._state = state
            if self._on_state_changed:
                self._on_state_changed(state)
    
    def _handle_data(self, data: bytes, address: Address) -> None:
        """Handle received data."""
        if self._on_data_received:
            self._on_data_received(data, address)
    
    def _handle_error(self, error: Exception) -> None:
        """Handle transport error."""
        self._set_state(TransportState.ERROR)
        if self._on_error:
            self._on_error(error)
    
    @abstractmethod
    async def bind(self, address: Address) -> None:
        """Bind to local address."""
        ...
    
    @abstractmethod
    async def connect(self, address: Address) -> None:
        """Connect to remote address."""
        ...
    
    @abstractmethod
    async def send(self, data: bytes, address: Address | None = None) -> None:
        """Send data to remote address."""
        ...
    
    @abstractmethod
    async def close(self) -> None:
        """Close transport."""
        ...


class DatagramTransport(Transport):
    """
    Base class for datagram (UDP) transports.
    """
    
    __slots__ = ("_protocol", "_asyncio_transport")
    
    def __init__(
        self,
        transport_type: TransportType = TransportType.UDP,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        super().__init__(transport_type, loop)
        self._protocol: DatagramProtocolHandler | None = None
        self._asyncio_transport: asyncio.DatagramTransport | None = None
    
    async def bind(self, address: Address) -> None:
        """Bind to local address and start listening."""
        if self._state != TransportState.DISCONNECTED:
            raise RuntimeError("Transport already bound")
        
        self._set_state(TransportState.CONNECTING)
        
        try:
            self._protocol = DatagramProtocolHandler(self)
            self._asyncio_transport, _ = await self._loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=address,
            )
            
            # Get actual bound address
            sockname = self._asyncio_transport.get_extra_info("sockname")
            if sockname:
                self._local_address = (sockname[0], sockname[1])
            
            self._set_state(TransportState.CONNECTED)
        except Exception as e:
            self._handle_error(e)
            raise
    
    async def connect(self, address: Address) -> None:
        """Set remote address for connected mode."""
        if self._state != TransportState.CONNECTED:
            # Bind to ephemeral port first
            await self.bind(("0.0.0.0", 0))
        
        self._remote_address = address
    
    async def send(self, data: bytes, address: Address | None = None) -> None:
        """Send datagram to address."""
        if not self._asyncio_transport:
            raise RuntimeError("Transport not bound")
        
        target = address or self._remote_address
        if not target:
            raise RuntimeError("No destination address")
        
        self._asyncio_transport.sendto(data, target)
    
    async def close(self) -> None:
        """Close transport."""
        if self._asyncio_transport:
            self._set_state(TransportState.CLOSING)
            self._asyncio_transport.close()
            self._asyncio_transport = None
            self._protocol = None
            self._set_state(TransportState.CLOSED)


class DatagramProtocolHandler(asyncio.DatagramProtocol):
    """
    Asyncio DatagramProtocol handler.
    
    Bridges asyncio protocol callbacks to Transport class.
    """
    
    __slots__ = ("_transport",)
    
    def __init__(self, transport: DatagramTransport):
        self._transport = transport
    
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when connection is established."""
        pass  # Already handled in bind()
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """Called when datagram is received."""
        self._transport._handle_data(data, addr)
    
    def error_received(self, exc: Exception) -> None:
        """Called on error."""
        self._transport._handle_error(exc)
    
    def connection_lost(self, exc: Exception | None) -> None:
        """Called when connection is lost."""
        if exc:
            self._transport._handle_error(exc)
        self._transport._set_state(TransportState.CLOSED)


class StreamTransport(Transport):
    """
    Base class for stream (TCP/TLS) transports.
    """
    
    __slots__ = ("_reader", "_writer", "_read_task")
    
    def __init__(
        self,
        transport_type: TransportType = TransportType.TCP,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        super().__init__(transport_type, loop)
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._read_task: asyncio.Task | None = None
    
    async def bind(self, address: Address) -> None:
        """Start TCP server on address."""
        raise NotImplementedError("TCP server mode not implemented")
    
    async def connect(self, address: Address) -> None:
        """Connect to remote address."""
        if self._state != TransportState.DISCONNECTED:
            raise RuntimeError("Transport already connected")
        
        self._set_state(TransportState.CONNECTING)
        
        try:
            self._reader, self._writer = await asyncio.open_connection(
                address[0], address[1]
            )
            
            # Get local address
            sockname = self._writer.get_extra_info("sockname")
            if sockname:
                self._local_address = (sockname[0], sockname[1])
            
            self._remote_address = address
            self._set_state(TransportState.CONNECTED)
            
            # Start read loop
            self._read_task = asyncio.create_task(self._read_loop())
        except Exception as e:
            self._handle_error(e)
            raise
    
    async def _read_loop(self) -> None:
        """Continuous read loop for incoming data."""
        try:
            while self._reader and self._state == TransportState.CONNECTED:
                data = await self._reader.read(65535)
                if not data:
                    break
                if self._remote_address:
                    self._handle_data(data, self._remote_address)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self._handle_error(e)
        finally:
            await self.close()
    
    async def send(self, data: bytes, address: Address | None = None) -> None:
        """Send data (address ignored for TCP)."""
        if not self._writer:
            raise RuntimeError("Transport not connected")
        
        self._writer.write(data)
        await self._writer.drain()
    
    async def close(self) -> None:
        """Close transport."""
        if self._read_task:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
            self._read_task = None
        
        if self._writer:
            self._set_state(TransportState.CLOSING)
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None
            self._set_state(TransportState.CLOSED)


