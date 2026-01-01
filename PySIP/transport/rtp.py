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
    RTP media session with RTCP support.
    
    Manages a single RTP stream with send/receive capabilities and
    RTCP for quality metrics (RFC 3550).
    
    Features:
    - Async packet send/receive
    - Automatic sequence number and timestamp
    - SSRC generation and validation
    - Packet statistics
    - RTCP sender/receiver reports
    - Jitter calculation
    
    Example:
        session = RTPSession(config)
        await session.start()
        
        session.on_packet(handle_audio)
        
        await session.send(audio_payload)
        
        # Get quality metrics
        print(f"Jitter: {session.stats.jitter}ms")
        print(f"Lost: {session.stats.packets_lost}")
        
        await session.stop()
    """
    
    __slots__ = (
        "_config",
        "_protocol",
        "_rtcp_protocol",
        "_loop",
        "_ssrc",
        "_sequence",
        "_timestamp",
        "_start_time",
        "_remote_address",
        "_on_packet",
        "_stats",
        "_running",
        # RTCP state
        "_rtcp_task",
        "_rtcp_interval",
        "_last_sr_ntp",
        "_last_sr_time",
        "_remote_ssrc",
        "_highest_seq",
        "_seq_cycles",
        "_last_seq",
        "_last_arrival",
        "_last_transit",
        "_jitter_estimate",
        # Per-interval statistics for fraction lost (RFC 3550)
        "_expected_prior",
        "_received_prior",
        # RTT calculation
        "_rtt",
        # SSRC collision detection
        "_ssrc_collision_count",
    )
    
    def __init__(
        self,
        config: RTPConfig | None = None,
        loop: asyncio.AbstractEventLoop | None = None,
    ):
        self._config = config or RTPConfig()
        self._loop = loop  # Will be set lazily in start() if None
        self._protocol: RTPProtocol | None = None
        self._rtcp_protocol: RTPProtocol | None = None  # RTCP uses same protocol class
        
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
        
        # RTCP state
        self._rtcp_task: asyncio.Task | None = None
        self._rtcp_interval = 5.0  # RTCP report interval in seconds
        self._last_sr_ntp: int = 0  # Last received SR NTP timestamp (compact)
        self._last_sr_time: float = 0.0  # Time when last SR was received
        self._remote_ssrc: int | None = None  # Remote party's SSRC
        self._highest_seq: int = 0  # Highest sequence number received
        self._seq_cycles: int = 0  # Sequence number wrap-around count
        self._last_seq: int = -1  # Last sequence number for reorder detection
        self._last_arrival: float = 0.0  # Last packet arrival time
        self._last_transit: float = 0.0  # Last transit time
        self._jitter_estimate: float = 0.0  # Jitter estimate (RFC 3550)
        
        # Per-interval statistics for fraction lost (RFC 3550 Section 6.4)
        self._expected_prior: int = 0  # Expected packets at last report
        self._received_prior: int = 0  # Received packets at last report
        
        # RTT calculation
        self._rtt: float = 0.0  # Round-trip time in seconds
        
        # SSRC collision detection (RFC 3550 Section 8.2)
        self._ssrc_collision_count: int = 0
    
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
        
        Creates UDP sockets for RTP and RTCP and begins listening.
        RTCP runs on RTP port + 1 per RFC 3550, or on the same port if
        RTCP-MUX (RFC 5761) is enabled.
        """
        if self._running:
            return
        
        # Get event loop lazily (must be in async context)
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        
        # Use unified handler for RTCP-MUX mode
        handler = self._handle_packet_mux if self._config.rtcp_mux else self._handle_packet
        
        self._protocol = RTPProtocol(
            session=self,
            on_packet_received=handler,
        )
        
        try:
            # Start RTP socket
            transport, _ = await self._loop.create_datagram_endpoint(
                lambda: self._protocol,
                local_addr=(self._config.local_ip, self._config.local_port),
            )
            self._start_time = time.monotonic()
            self._running = True
            logger.debug(f"RTP session started on {self._protocol._local_address}")
            
            if self._config.rtcp_mux:
                # RTCP-MUX mode: use same socket for RTCP
                self._rtcp_protocol = self._protocol
                logger.debug("RTCP-MUX enabled - RTCP on same port as RTP")
            else:
                # Standard mode: separate RTCP socket on port + 1
                rtcp_port = self._config.local_port + 1
                self._rtcp_protocol = RTPProtocol(
                    session=self,
                    on_packet_received=self._handle_rtcp_packet,
                )
                try:
                    await self._loop.create_datagram_endpoint(
                        lambda: self._rtcp_protocol,
                        local_addr=(self._config.local_ip, rtcp_port),
                    )
                    logger.debug(f"RTCP started on port {rtcp_port}")
                except OSError as e:
                    logger.warning(f"Failed to bind RTCP socket on port {rtcp_port}: {e}")
                    # RTCP is optional, continue without it
            
            # Start RTCP report task
            self._rtcp_task = asyncio.create_task(self._rtcp_loop())
                
        except OSError as e:
            raise BindError(
                self._config.local_ip,
                self._config.local_port,
                f"Failed to bind RTP socket: {e}"
            )
    
    async def stop(self) -> None:
        """Stop RTP session and RTCP."""
        if not self._running:
            return
        
        self._running = False
        
        # Stop RTCP task
        if self._rtcp_task:
            self._rtcp_task.cancel()
            try:
                await self._rtcp_task
            except asyncio.CancelledError:
                pass
            self._rtcp_task = None
        
        # Send RTCP BYE
        if self._rtcp_protocol and self._remote_address:
            try:
                await self._send_rtcp_bye()
            except Exception:
                pass
        
        # Close sockets
        if self._protocol:
            self._protocol.close()
            self._protocol = None
        
        # Only close RTCP socket if not using RTCP-MUX (separate socket)
        if self._rtcp_protocol and not self._config.rtcp_mux:
            self._rtcp_protocol.close()
        self._rtcp_protocol = None
        
        logger.debug("RTP/RTCP session stopped")
    
    def _handle_packet_mux(self, data: bytes, addr: Address) -> None:
        """
        Handle received packet in RTCP-MUX mode (RFC 5761).
        
        Differentiates RTP from RTCP by examining the payload type byte.
        RTCP packet types are 200-204, while RTP payload types are typically < 128.
        """
        if len(data) < 2:
            return
        
        # Second byte contains payload type (for RTP) or packet type (for RTCP)
        pt = data[1] & 0x7F if (data[0] >> 6) == 2 else 0
        
        # RTCP packet types: 200 (SR), 201 (RR), 202 (SDES), 203 (BYE), 204 (APP)
        # RTP payload types are typically 0-127
        # RFC 5761 says to check if pt is in range 200-204 (RTCP) vs 0-127 (RTP)
        if 200 <= data[1] <= 204:
            self._handle_rtcp_packet(data, addr)
        else:
            self._handle_packet(data, addr)
    
    def _handle_packet(self, data: bytes, addr: Address) -> None:
        """Handle received RTP packet and update statistics."""
        self._stats.packets_received += 1
        self._stats.bytes_received += len(data)
        
        # Update remote address from first packet if not set
        if not self._remote_address:
            self._remote_address = addr
        
        # Parse RTP header for statistics and collision detection
        if len(data) >= 12:
            try:
                # Check for SSRC collision (RFC 3550 Section 8.2)
                ssrc = struct.unpack_from("!I", data, 8)[0]
                if ssrc == self._ssrc and self._remote_ssrc is not None:
                    # Collision detected - we received a packet with our own SSRC
                    # from a different source
                    self._handle_ssrc_collision()
                    return
                
                self._update_reception_stats(data)
            except Exception:
                pass
        
        # Forward to callback
        if self._on_packet:
            self._on_packet(data, addr)
    
    def _update_reception_stats(self, data: bytes) -> None:
        """Update reception statistics from RTP packet (RFC 3550 A.8)."""
        # Parse header
        byte0, byte1, seq = struct.unpack_from("!BBH", data, 0)
        ssrc = struct.unpack_from("!I", data, 8)[0]
        rtp_timestamp = struct.unpack_from("!I", data, 4)[0]
        
        # Track remote SSRC
        if self._remote_ssrc is None:
            self._remote_ssrc = ssrc
        
        # Update sequence number tracking
        if self._last_seq == -1:
            self._last_seq = seq
            self._highest_seq = seq
        else:
            # Check for wrap-around
            delta = seq - self._highest_seq
            if delta > 0:
                if delta > 32768:
                    # Likely a reorder, not an advance
                    pass
                else:
                    self._highest_seq = seq
                    if seq < self._last_seq:
                        # Wrap-around detected
                        self._seq_cycles += 1
            elif delta < -32768:
                # Wrap-around with advance
                self._seq_cycles += 1
                self._highest_seq = seq
            
            # Count lost packets (simplified)
            expected_delta = (seq - self._last_seq) & 0xFFFF
            if expected_delta > 1 and expected_delta < 32768:
                self._stats.packets_lost += expected_delta - 1
        
        self._last_seq = seq
        
        # Calculate jitter (RFC 3550 A.8)
        arrival_time = time.monotonic()
        if self._last_arrival > 0:
            # Transit time difference
            transit = arrival_time - (rtp_timestamp / self._config.clock_rate)
            if self._last_transit > 0:
                d = abs(transit - self._last_transit)
                # Update jitter estimate: J = J + (|D| - J) / 16
                self._jitter_estimate += (d - self._jitter_estimate) / 16.0
                # Convert to milliseconds for stats
                self._stats.jitter = self._jitter_estimate * 1000
            self._last_transit = transit
        
        self._last_arrival = arrival_time
    
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
    
    # === RTCP Methods ===
    
    def _handle_rtcp_packet(self, data: bytes, addr: Address) -> None:
        """Handle received RTCP packet."""
        from ..protocol.rtp.rtcp import parse_rtcp_packet, SenderReport, ReceiverReport, ntp_to_compact
        
        try:
            packet = parse_rtcp_packet(data)
            
            if isinstance(packet, SenderReport):
                # Check for SSRC collision (RFC 3550 Section 8.2)
                if packet.ssrc == self._ssrc:
                    self._handle_ssrc_collision()
                    return
                
                # Store last SR info for DLSR calculation
                self._last_sr_ntp = ntp_to_compact(
                    packet.ntp_timestamp_msw, 
                    packet.ntp_timestamp_lsw
                )
                self._last_sr_time = time.monotonic()
                
                # Calculate RTT from report blocks that reference us
                for block in packet.report_blocks:
                    if block.ssrc == self._ssrc and block.lsr > 0:
                        # RTT = current_time - LSR - DLSR
                        # LSR and DLSR are in 1/65536 seconds
                        current_ntp = ntp_to_compact(*__import__('PySIP.protocol.rtp.rtcp', fromlist=['get_ntp_timestamp']).get_ntp_timestamp())
                        rtt_ntp = current_ntp - block.lsr - block.dlsr
                        self._rtt = rtt_ntp / 65536.0
                        self._stats.rtt = self._rtt * 1000  # Convert to ms
                        logger.debug(f"RTT calculated: {self._rtt * 1000:.1f}ms")
                
                logger.debug(f"Received SR from SSRC {packet.ssrc}")
            
            elif isinstance(packet, ReceiverReport):
                # Check for SSRC collision
                if packet.ssrc == self._ssrc:
                    self._handle_ssrc_collision()
                    return
                
                # Calculate RTT from report blocks that reference us
                for block in packet.report_blocks:
                    if block.ssrc == self._ssrc and block.lsr > 0:
                        from ..protocol.rtp.rtcp import get_ntp_timestamp, ntp_to_compact
                        current_ntp = ntp_to_compact(*get_ntp_timestamp())
                        rtt_ntp = current_ntp - block.lsr - block.dlsr
                        self._rtt = rtt_ntp / 65536.0
                        self._stats.rtt = self._rtt * 1000  # Convert to ms
                
                logger.debug(f"Received RR from SSRC {packet.ssrc}")
                
        except Exception as e:
            logger.debug(f"Failed to parse RTCP packet: {e}")
    
    def _handle_ssrc_collision(self) -> None:
        """
        Handle SSRC collision (RFC 3550 Section 8.2).
        
        When we detect another source using our SSRC, we must:
        1. Send BYE with old SSRC
        2. Choose a new random SSRC
        3. Reset sequence number
        """
        old_ssrc = self._ssrc
        self._ssrc_collision_count += 1
        
        logger.warning(f"SSRC collision detected! Old SSRC: {old_ssrc:#x}")
        
        # Send BYE with old SSRC (best effort, don't wait)
        if self._rtcp_protocol and self._remote_address:
            try:
                from ..protocol.rtp.rtcp import Goodbye
                bye = Goodbye(ssrc_list=[old_ssrc], reason="SSRC collision")
                data = bye.serialize()
                rtcp_addr = (self._remote_address[0], self._remote_address[1] + 1)
                self._rtcp_protocol.send_packet(data, rtcp_addr)
            except Exception:
                pass
        
        # Generate new SSRC
        self._ssrc = random.randint(0, 0xFFFFFFFF)
        
        # Reset sequence number to avoid confusion
        self._sequence = random.randint(0, 65535)
        
        logger.info(f"New SSRC assigned: {self._ssrc:#x} (collision #{self._ssrc_collision_count})")
    
    def _compute_rtcp_interval(self) -> float:
        """
        Compute RTCP transmission interval with randomization (RFC 3550 Section 6.2).
        
        The interval is randomized to prevent synchronization of reports
        from multiple sources, which could cause network congestion.
        
        Returns:
            Interval in seconds, randomized between 0.5x and 1.5x base interval
        """
        # Base interval (minimum 5 seconds per RFC 3550)
        base_interval = max(5.0, self._rtcp_interval)
        
        # Apply randomization factor [0.5, 1.5) to prevent synchronization
        # RFC 3550 recommends: interval * random [0.5, 1.5)
        randomization = 0.5 + random.random()  # Range [0.5, 1.5)
        
        return base_interval * randomization
    
    async def _rtcp_loop(self) -> None:
        """Periodic RTCP report transmission with randomized intervals."""
        try:
            while self._running:
                # Use randomized interval per RFC 3550 Section 6.2
                interval = self._compute_rtcp_interval()
                await asyncio.sleep(interval)
                
                if not self._running or not self._remote_address:
                    continue
                
                try:
                    # Send SR if we've sent packets, RR otherwise
                    if self._stats.packets_sent > 0:
                        await self._send_rtcp_sr()
                    elif self._remote_ssrc is not None:
                        await self._send_rtcp_rr()
                except Exception as e:
                    logger.debug(f"Failed to send RTCP report: {e}")
                    
        except asyncio.CancelledError:
            pass
    
    async def _send_rtcp_sr(self) -> None:
        """Send RTCP Sender Report."""
        from ..protocol.rtp.rtcp import SenderReport, ReportBlock, SDESChunk, SDESItem, SDESType, SourceDescription, get_ntp_timestamp
        
        if not self._rtcp_protocol or not self._remote_address:
            return
        
        ntp_msw, ntp_lsw = get_ntp_timestamp()
        
        # Build report blocks for sources we've received from
        report_blocks = []
        if self._remote_ssrc is not None:
            # Calculate extended highest sequence number
            extended_max = self._highest_seq + self._seq_cycles * 65536
            
            # Calculate fraction lost per RFC 3550 Section 6.4.1
            # Fraction lost is the fraction of packets lost since the last SR/RR
            expected = extended_max - self._expected_prior
            received = self._stats.packets_received - self._received_prior
            lost_interval = expected - received
            
            fraction_lost = 0
            if expected > 0 and lost_interval > 0:
                fraction_lost = min(int((lost_interval * 256) / expected), 255)
            
            # Update prior values for next interval
            self._expected_prior = extended_max
            self._received_prior = self._stats.packets_received
            
            # Calculate DLSR (delay since last SR)
            dlsr = 0
            if self._last_sr_time > 0:
                delay = time.monotonic() - self._last_sr_time
                dlsr = int(delay * 65536)  # Units of 1/65536 seconds
            
            block = ReportBlock(
                ssrc=self._remote_ssrc,
                fraction_lost=fraction_lost,
                cumulative_lost=self._stats.packets_lost,
                highest_seq=extended_max,
                jitter=int(self._jitter_estimate * self._config.clock_rate),
                lsr=self._last_sr_ntp,
                dlsr=dlsr,
            )
            report_blocks.append(block)
        
        sr = SenderReport(
            ssrc=self._ssrc,
            ntp_timestamp_msw=ntp_msw,
            ntp_timestamp_lsw=ntp_lsw,
            rtp_timestamp=self._timestamp,
            sender_packet_count=self._stats.packets_sent,
            sender_octet_count=self._stats.bytes_sent,
            report_blocks=report_blocks,
        )
        
        # Add SDES with CNAME
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=self._ssrc,
                items=[SDESItem(SDESType.CNAME, f"pysip@{self._config.local_ip}")]
            )
        ])
        
        # Compound packet: SR + SDES
        data = sr.serialize() + sdes.serialize()
        
        # Use same port for RTCP-MUX, otherwise port + 1
        if self._config.rtcp_mux:
            rtcp_addr = self._remote_address
        else:
            rtcp_addr = (self._remote_address[0], self._remote_address[1] + 1)
        self._rtcp_protocol.send_packet(data, rtcp_addr)
        logger.debug(f"Sent RTCP SR to {rtcp_addr}")
    
    async def _send_rtcp_rr(self) -> None:
        """Send RTCP Receiver Report."""
        from ..protocol.rtp.rtcp import ReceiverReport, ReportBlock, SDESChunk, SDESItem, SDESType, SourceDescription
        
        if not self._rtcp_protocol or not self._remote_address or self._remote_ssrc is None:
            return
        
        # Calculate extended highest sequence number
        extended_max = self._highest_seq + self._seq_cycles * 65536
        
        # Calculate fraction lost per RFC 3550 Section 6.4.1
        expected = extended_max - self._expected_prior
        received = self._stats.packets_received - self._received_prior
        lost_interval = expected - received
        
        fraction_lost = 0
        if expected > 0 and lost_interval > 0:
            fraction_lost = min(int((lost_interval * 256) / expected), 255)
        
        # Update prior values for next interval
        self._expected_prior = extended_max
        self._received_prior = self._stats.packets_received
        
        # Calculate DLSR
        dlsr = 0
        if self._last_sr_time > 0:
            delay = time.monotonic() - self._last_sr_time
            dlsr = int(delay * 65536)
        
        rr = ReceiverReport(
            ssrc=self._ssrc,
            report_blocks=[
                ReportBlock(
                    ssrc=self._remote_ssrc,
                    fraction_lost=fraction_lost,
                    cumulative_lost=self._stats.packets_lost,
                    highest_seq=extended_max,
                    jitter=int(self._jitter_estimate * self._config.clock_rate),
                    lsr=self._last_sr_ntp,
                    dlsr=dlsr,
                )
            ],
        )
        
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=self._ssrc,
                items=[SDESItem(SDESType.CNAME, f"pysip@{self._config.local_ip}")]
            )
        ])
        
        data = rr.serialize() + sdes.serialize()
        
        # Use same port for RTCP-MUX, otherwise port + 1
        if self._config.rtcp_mux:
            rtcp_addr = self._remote_address
        else:
            rtcp_addr = (self._remote_address[0], self._remote_address[1] + 1)
        self._rtcp_protocol.send_packet(data, rtcp_addr)
        logger.debug(f"Sent RTCP RR to {rtcp_addr}")
    
    async def _send_rtcp_bye(self) -> None:
        """Send RTCP BYE packet."""
        from ..protocol.rtp.rtcp import Goodbye
        
        if not self._rtcp_protocol or not self._remote_address:
            return
        
        bye = Goodbye(ssrc_list=[self._ssrc], reason="Session ended")
        data = bye.serialize()
        
        # Use same port for RTCP-MUX, otherwise port + 1
        if self._config.rtcp_mux:
            rtcp_addr = self._remote_address
        else:
            rtcp_addr = (self._remote_address[0], self._remote_address[1] + 1)
        self._rtcp_protocol.send_packet(data, rtcp_addr)
        logger.debug(f"Sent RTCP BYE to {rtcp_addr}")


class RTPStats:
    """RTP session statistics."""
    
    __slots__ = (
        "packets_sent",
        "packets_received",
        "bytes_sent",
        "bytes_received",
        "packets_lost",
        "jitter",
        "rtt",
    )
    
    def __init__(self):
        self.packets_sent = 0
        self.packets_received = 0
        self.bytes_sent = 0
        self.bytes_received = 0
        self.packets_lost = 0
        self.jitter = 0.0
        self.rtt = 0.0  # Round-trip time in milliseconds
    
    def __repr__(self) -> str:
        return (
            f"RTPStats(sent={self.packets_sent}, recv={self.packets_received}, "
            f"lost={self.packets_lost}, jitter={self.jitter:.2f}ms, rtt={self.rtt:.2f}ms)"
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
        self._loop = loop  # Will be set lazily in create_session() if None
    
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
        
        # Get event loop lazily (must be in async context)
        if self._loop is None:
            self._loop = asyncio.get_running_loop()
        
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


