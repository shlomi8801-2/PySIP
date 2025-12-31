"""
RTP Transport

Async RTP media transport using asyncio.DatagramProtocol.
Zero-thread design for high concurrency.
"""

from __future__ import annotations

import asyncio
import logging
import random
import struct
import time
from typing import TYPE_CHECKING, Callable

from ..exceptions import RTPError, BindError
from ..types import Address, CodecType, RTPConfig, TransportState

if TYPE_CHECKING:
    from ..protocol.rtp import RTPPacket

logger = logging.getLogger(__name__)


class RTPProtocol(asyncio.DatagramProtocol):
    """
    Asyncio DatagramProtocol for RTP media.
    
    Features:
    - Zero-copy packet handling
    - Non-blocking send/receive
    - Automatic SSRC generation
    - Sequence number tracking
    - Timestamp management
    """
    
    __slots__ = (
        "_transport",
        "_session",
        "_on_packet_received",
        "_on_error",
        "_local_address",
    )
    
    def __init__(
        self,
        session: "RTPSession",
        on_packet_received: Callable[[bytes, Address], None] | None = None,
    ):
        self._transport: asyncio.DatagramTransport | None = None
        self._session = session
        self._on_packet_received = on_packet_received
        self._on_error: Callable[[Exception], None] | None = None
        self._local_address: Address | None = None
    
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        """Called when socket is ready."""
        self._transport = transport
        sockname = transport.get_extra_info("sockname")
        if sockname:
            self._local_address = (sockname[0], sockname[1])
    
    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        """
        Called when RTP packet is received.
        
        This is the hot path - keep it fast!
        """
        if self._on_packet_received:
            self._on_packet_received(data, addr)
    
    def error_received(self, exc: Exception) -> None:
        """Called on socket error."""
        logger.error(f"RTP socket error: {exc}")
        if self._on_error:
            self._on_error(exc)
    
    def connection_lost(self, exc: Exception | None) -> None:
        """Called when socket is closed."""
        if exc:
            logger.error(f"RTP connection lost: {exc}")
    
    def send_packet(self, data: bytes, addr: Address) -> None:
        """
        Send RTP packet.
        
        Non-blocking - queues to OS buffer.
        """
        if self._transport:
            self._transport.sendto(data, addr)
    
    def close(self) -> None:
        """Close the socket."""
        if self._transport:
            self._transport.close()
            self._transport = None


class RTPSession:
    """
    RTP media session.
    
    Manages a single RTP stream with send/receive capabilities.
    
    Features:
    - Async packet send/receive
    - Automatic sequence number and timestamp
    - SSRC generation and validation
    - Packet statistics
    
    Example:
        session = RTPSession(config)
        await session.start()
        
        session.on_packet(handle_audio)
        
        await session.send(audio_payload)
        
        await session.stop()
    """
    
    __slots__ = (
        "_config",
        "_protocol",
        "_loop",
        "_ssrc",
        "_sequence",
        "_timestamp",
        "_start_time",
        "_remote_address",
        "_on_packet",
        "_stats",
        "_running",
    )
    
    def __init__(
        self,
        config: RTPConfig | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._config = config or RTPConfig()
        self._loop = loop or asyncio.get_event_loop()
        self._protocol: RTPProtocol | None = None
        
        # RTP state
        self._ssrc = self._config.ssrc or random.randint(0, 0xFFFFFFFF)
        self._sequence = random.randint(0, 65535)
        self._timestamp = random.randint(0, 0xFFFFFFFF)
        self._start_time: float | None = None
        
        # Remote endpoint
        self._remote_address: Address | None = None
        if self._config.remote_ip and self._config.remote_port:
            self._remote_address = (self._config.remote_ip, self._config.remote_port)
        
        # Callbacks
        self._on_packet: Callable[[bytes, Address], None] | None = None
        
        # Statistics
        self._stats = RTPStats()
        self._running = False
    
    @property
    def local_address(self) -> Address | None:
        """Local bound address."""
        if self._protocol:
            return self._protocol._local_address
        return None
    
    @property
    def remote_address(self) -> Address | None:
        """Remote endpoint address."""
        return self._remote_address
    
    @property
    def ssrc(self) -> int:
        """Session SSRC identifier."""
        return self._ssrc
    
    @property
    def stats(self) -> "RTPStats":
        """Session statistics."""
        return self._stats
    
    @property
    def is_running(self) -> bool:
        """Check if session is active."""
        return self._running
    
    def set_remote_address(self, address: Address) -> None:
        """Set remote endpoint address."""
        self._remote_address = address
    
    def on_packet(self, callback: Callable[[bytes, Address], None]) -> None:
        """Set callback for received packets."""
        self._on_packet = callback
    
    async def start(self) -> None:
        """
        Start RTP session.
        
        Creates UDP socket and begins listening.
        """
        if self._running:
            return
        
        self._protocol = RTPProtocol(
            session=self,
            on_packet_received=self._handle_packet,
        )
        
        try:
            transport, _ = await self._loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=(self._config.local_ip, self._config.local_port),
            )
            self._start_time = time.monotonic()
            self._running = True
            logger.debug(f"RTP session started on {self._protocol._local_address}")
        except OSError as e:
            raise BindError(
                self._config.local_ip,
                self._config.local_port,
                f"Failed to bind RTP socket: {e}"
            )
    
    async def stop(self) -> None:
        """Stop RTP session."""
        if not self._running:
            return
        
        self._running = False
        if self._protocol:
            self._protocol.close()
            self._protocol = None
        
        logger.debug("RTP session stopped")
    
    def _handle_packet(self, data: bytes, addr: Address) -> None:
        """Handle received RTP packet."""
        self._stats.packets_received += 1
        self._stats.bytes_received += len(data)
        
        # Update remote address from first packet if not set
        if not self._remote_address:
            self._remote_address = addr
        
        # Forward to callback
        if self._on_packet:
            self._on_packet(data, addr)
    
    def send(self, payload: bytes, marker: bool = False) -> None:
        """
        Send RTP packet.
        
        Builds RTP header and sends packet.
        Non-blocking - returns immediately.
        
        Args:
            payload: Audio payload (encoded)
            marker: RTP marker bit (e.g., start of talk spurt)
        """
        if not self._running or not self._protocol or not self._remote_address:
            return
        
        # Build RTP header (12 bytes)
        # Version=2, Padding=0, Extension=0, CSRC count=0
        byte0 = 0x80
        
        # Marker bit + payload type
        byte1 = (0x80 if marker else 0x00) | (self._config.payload_type & 0x7F)
        
        header = struct.pack(
            "!BBHII",
            byte0,
            byte1,
            self._sequence & 0xFFFF,
            self._timestamp & 0xFFFFFFFF,
            self._ssrc,
        )
        
        packet = header + payload
        
        # Send
        self._protocol.send_packet(packet, self._remote_address)
        
        # Update state
        self._sequence = (self._sequence + 1) & 0xFFFF
        # Timestamp increment: samples per packet (e.g., 160 for 20ms @ 8kHz)
        samples_per_packet = (self._config.clock_rate * self._config.ptime) // 1000
        self._timestamp = (self._timestamp + samples_per_packet) & 0xFFFFFFFF
        
        # Stats
        self._stats.packets_sent += 1
        self._stats.bytes_sent += len(packet)
    
    async def send_async(self, payload: bytes, marker: bool = False) -> None:
        """Async wrapper for send (for API consistency)."""
        self.send(payload, marker)


class RTPStats:
    """RTP session statistics."""
    
    __slots__ = (
        "packets_sent",
        "packets_received",
        "bytes_sent",
        "bytes_received",
        "packets_lost",
        "jitter",
    )
    
    def __init__(self):
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.packets_lost = 0
        self.jitter = 0.0
    
    def __repr__(self) -> str:
        return (
            f"RTPStats(sent={self.packets_sent}, recv={self.packets_received}, "
            f"lost={self.packets_lost}, jitter={self.jitter:.2f}ms)"
        )


class RTPTransport:
    """
    High-level RTP transport manager.
    
    Manages multiple RTP sessions and port allocation.
    """
    
    __slots__ = (
        "_sessions",
        "_port_range",
        "_next_port",
        "_loop",
    )
    
    def __init__(
        self,
        port_range: tuple[int, int] = (10000, 20000),
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._sessions: dict[str, RTPSession] = {}
        self._port_range = port_range
        self._next_port = port_range[0]
        self._loop = loop or asyncio.get_event_loop()
    
    def _allocate_port(self) -> int:
        """Allocate next available port."""
        port = self._next_port
        self._next_port += 2  # RTP uses even ports, RTCP uses odd
        
        if self._next_port >= self._port_range[1]:
            self._next_port = self._port_range[0]
        
        return port
    
    async def create_session(
        self,
        session_id: str,
        config: RTPConfig | None = None,
    ) -> RTPSession:
        """
        Create new RTP session.
        
        Args:
            session_id: Unique session identifier
            config: Session configuration
            
        Returns:
            Created RTPSession
        """
        if session_id in self._sessions:
            raise RTPError(f"Session already exists: {session_id}")
        
        # Auto-assign port if not specified
        cfg = config or RTPConfig()
        if cfg.local_port == 0:
            cfg.local_port = self._allocate_port()
        
        session = RTPSession(cfg, self._loop)
        await session.start()
        
        self._sessions[session_id] = session
        return session
    
    async def destroy_session(self, session_id: str) -> None:
        """Destroy RTP session."""
        if session_id in self._sessions:
            session = self._sessions.pop(session_id)
            await session.stop()
    
    def get_session(self, session_id: str) -> RTPSession | None:
        """Get session by ID."""
        return self._sessions.get(session_id)
    
    async def close(self) -> None:
        """Close all sessions."""
        for session_id in list(self._sessions.keys()):
            await self.destroy_session(session_id)


