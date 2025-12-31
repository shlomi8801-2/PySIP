"""
UDP Transport for SIP Signaling

Async UDP transport implementation using asyncio.DatagramProtocol.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Callable

from ..exceptions import BindError, SendError, TransportError
from ..types import Address, TransportState, TransportType
from .base import DatagramTransport

if TYPE_CHECKING:
    from ..protocol.sip import SIPMessage

logger = logging.getLogger(__name__)


class UDPTransport(DatagramTransport):
    """
    Async UDP transport for SIP signaling.
    
    Features:
    - Non-blocking send/receive via asyncio
    - Automatic retransmission support
    - Connection state management
    
    Example:
        transport = UDPTransport()
        await transport.bind(("0.0.0.0", 5060))
        
        transport.on_data_received(handle_message)
        
        await transport.send(message_bytes, ("sip.server.com", 5060))
    """
    
    __slots__ = (
        "_retransmit_timers",
        "_pending_transactions",
        "_max_retransmits",
        "_t1",  # RTT estimate
    )
    
    def __init__(
        self,
        loop: asyncio.AbstractEventLoop | None = None,
        t1: float = 0.5,  # 500ms default RTT estimate
        max_retransmits: int = 7,
    ):
        super().__init__(TransportType.UDP, loop)
        self._retransmit_timers: dict[str, asyncio.TimerHandle] = {}
        self._pending_transactions: dict[str, tuple[bytes, Address, int]] = {}
        self._max_retransmits = max_retransmits
        self._t1 = t1
    
    async def send_with_retransmit(
        self,
        data: bytes,
        address: Address,
        transaction_id: str,
    ) -> None:
        """
        Send data with automatic retransmission.
        
        Uses RFC 3261 exponential backoff: T1, 2*T1, 4*T1, etc.
        
        Args:
            data: Message bytes to send
            address: Destination (IP, port)
            transaction_id: Unique transaction identifier
        """
        if transaction_id in self._pending_transactions:
            # Cancel existing retransmission
            self.cancel_retransmit(transaction_id)
        
        # Store transaction
        self._pending_transactions[transaction_id] = (data, address, 0)
        
        # Send initial packet
        await self.send(data, address)
        
        # Schedule first retransmit
        self._schedule_retransmit(transaction_id, self._t1)
    
    def cancel_retransmit(self, transaction_id: str) -> None:
        """Cancel retransmission for a transaction."""
        if transaction_id in self._retransmit_timers:
            self._retransmit_timers[transaction_id].cancel()
            del self._retransmit_timers[transaction_id]
        
        if transaction_id in self._pending_transactions:
            del self._pending_transactions[transaction_id]
    
    def _schedule_retransmit(self, transaction_id: str, delay: float) -> None:
        """Schedule retransmission timer."""
        handle = self._loop.call_later(
            delay,
            self._do_retransmit,
            transaction_id,
        )
        self._retransmit_timers[transaction_id] = handle
    
    def _do_retransmit(self, transaction_id: str) -> None:
        """Execute retransmission."""
        if transaction_id not in self._pending_transactions:
            return
        
        data, address, count = self._pending_transactions[transaction_id]
        
        if count >= self._max_retransmits:
            # Max retransmits reached - transaction failed
            logger.warning(f"Transaction {transaction_id} timed out after {count} retransmits")
            self.cancel_retransmit(transaction_id)
            return
        
        # Send retransmit
        if self._asyncio_transport:
            self._asyncio_transport.sendto(data, address)
            logger.debug(f"Retransmit {count + 1} for transaction {transaction_id}")
        
        # Update count
        self._pending_transactions[transaction_id] = (data, address, count + 1)
        
        # Schedule next retransmit with exponential backoff
        # T1, 2*T1, 4*T1, 4*T1, 4*T1... (capped at 4*T1 per RFC 3261)
        next_delay = min(self._t1 * (2 ** count), self._t1 * 4)
        self._schedule_retransmit(transaction_id, next_delay)
    
    async def close(self) -> None:
        """Close transport and cancel all pending retransmissions."""
        # Cancel all retransmit timers
        for timer in self._retransmit_timers.values():
            timer.cancel()
        self._retransmit_timers.clear()
        self._pending_transactions.clear()
        
        await super().close()


class UDPServer:
    """
    UDP server for listening on a port.
    
    Wraps UDPTransport for server-mode operation.
    """
    
    __slots__ = ("_transport", "_address", "_message_handler")
    
    def __init__(
        self,
        address: Address,
        message_handler: Callable[[bytes, Address], None] | None = None,
    ):
        self._address = address
        self._transport = UDPTransport()
        self._message_handler = message_handler
    
    async def start(self) -> None:
        """Start listening on configured address."""
        if self._message_handler:
            self._transport.on_data_received(self._message_handler)
        
        await self._transport.bind(self._address)
        logger.info(f"UDP server listening on {self._address[0]}:{self._address[1]}")
    
    async def stop(self) -> None:
        """Stop the server."""
        await self._transport.close()
        logger.info("UDP server stopped")
    
    @property
    def transport(self) -> UDPTransport:
        """Get underlying transport."""
        return self._transport
    
    @property
    def local_address(self) -> Address | None:
        """Get local bound address."""
        return self._transport.local_address
    
    async def send(self, data: bytes, address: Address) -> None:
        """Send data to address."""
        await self._transport.send(data, address)
    
    async def __aenter__(self) -> "UDPServer":
        await self.start()
        return self
    
    async def __aexit__(self, *exc) -> None:
        await self.stop()


