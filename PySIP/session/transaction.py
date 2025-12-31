"""
SIP Transaction Handling

RFC 3261 compliant transaction state machines.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

from ..types import TransactionState

if TYPE_CHECKING:
    from ..protocol.sip import SIPRequest, SIPResponse
    from ..transport import UDPTransport

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TransactionId:
    """
    Transaction identifier.
    
    Per RFC 3261, transaction is identified by:
    - Branch parameter from Via header
    - Method (for CANCEL matching)
    """
    
    branch: str
    method: str
    
    def __hash__(self) -> int:
        return hash((self.branch, self.method))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, TransactionId):
            return False
        return self.branch == other.branch and self.method == other.method
    
    def __str__(self) -> str:
        return f"{self.method}:{self.branch}"


# Timer values (RFC 3261 Section 17.1.1.1)
T1 = 0.5  # RTT estimate (500ms)
T2 = 4.0  # Maximum retransmit interval (4s)
T4 = 5.0  # Maximum duration for message to remain in network (5s)


class ClientTransaction:
    """
    Client transaction (UAC side).
    
    Handles request retransmission and response matching.
    
    State machine:
    - CALLING/TRYING -> PROCEEDING -> COMPLETED -> TERMINATED
    
    Example:
        transaction = ClientTransaction(transport, request)
        response = await transaction.send()
    """
    
    __slots__ = (
        "_id",
        "_transport",
        "_request",
        "_state",
        "_remote_address",
        "_response_future",
        "_final_response",
        "_retransmit_task",
        "_timeout_task",
        "_retransmit_count",
        "_created_at",
    )
    
    def __init__(
        self,
        transport: "UDPTransport",
        request: "SIPRequest",
        remote_address: tuple[str, int],
    ):
        # Extract branch from Via header
        via = request.headers.get("via", "")
        branch = ""
        if "branch=" in via:
            start = via.find("branch=") + 7
            end = via.find(";", start)
            if end == -1:
                end = len(via)
            branch = via[start:end]
        
        method = request.method.value if hasattr(request.method, 'value') else str(request.method)
        
        self._id = TransactionId(branch=branch, method=method)
        self._transport = transport
        self._request = request
        self._state = TransactionState.INIT
        self._remote_address = remote_address
        self._response_future: asyncio.Future | None = None
        self._final_response: "SIPResponse | None" = None
        self._retransmit_task: asyncio.Task | None = None
        self._timeout_task: asyncio.Task | None = None
        self._retransmit_count = 0
        self._created_at = time.time()
    
    @property
    def id(self) -> TransactionId:
        """Transaction identifier."""
        return self._id
    
    @property
    def state(self) -> TransactionState:
        """Current transaction state."""
        return self._state
    
    @property
    def request(self) -> "SIPRequest":
        """Original request."""
        return self._request
    
    async def send(
        self,
        timeout: float = 32.0,
    ) -> "SIPResponse | None":
        """
        Send request and wait for final response.
        
        Args:
            timeout: Maximum wait time for response
            
        Returns:
            Final response or None on timeout
        """
        from ..protocol.sip.builder import serialize_request
        
        # Serialize request
        data = serialize_request(self._request)
        
        # Set initial state based on method
        if self._request.is_invite:
            self._state = TransactionState.CALLING
        else:
            self._state = TransactionState.TRYING
        
        # Create response future
        self._response_future = asyncio.get_event_loop().create_future()
        
        try:
            # Send initial request
            await self._transport.send(data, self._remote_address)
            logger.debug(f"Transaction {self._id}: sent request")
            
            # Start retransmission for UDP
            self._retransmit_task = asyncio.create_task(
                self._retransmit_loop(data)
            )
            
            # Wait for response with timeout
            response = await asyncio.wait_for(
                self._response_future,
                timeout=timeout,
            )
            
            return response
        
        except asyncio.TimeoutError:
            logger.warning(f"Transaction {self._id}: timeout")
            self._state = TransactionState.TERMINATED
            return None
        
        finally:
            # Cleanup
            if self._retransmit_task:
                self._retransmit_task.cancel()
                try:
                    await self._retransmit_task
                except asyncio.CancelledError:
                    pass
    
    async def _retransmit_loop(self, data: bytes) -> None:
        """Retransmission loop for UDP."""
        interval = T1
        
        try:
            while self._state in (TransactionState.CALLING, TransactionState.TRYING):
                await asyncio.sleep(interval)
                
                if self._state not in (TransactionState.CALLING, TransactionState.TRYING):
                    break
                
                self._retransmit_count += 1
                await self._transport.send(data, self._remote_address)
                logger.debug(f"Transaction {self._id}: retransmit {self._retransmit_count}")
                
                # Exponential backoff, capped at T2
                interval = min(interval * 2, T2)
        
        except asyncio.CancelledError:
            pass
    
    def on_response(self, response: "SIPResponse") -> bool:
        """
        Handle incoming response.
        
        Args:
            response: Received response
            
        Returns:
            True if response was handled
        """
        status = response.status_code
        
        if self._state == TransactionState.TERMINATED:
            return False
        
        # Provisional response (1xx)
        if 100 <= status < 200:
            if self._state in (TransactionState.CALLING, TransactionState.TRYING):
                self._state = TransactionState.PROCEEDING
                # Don't complete future yet - wait for final
                return True
        
        # Final response (2xx-6xx)
        elif status >= 200:
            self._final_response = response
            
            if self._request.is_invite:
                self._state = TransactionState.COMPLETED
            else:
                self._state = TransactionState.COMPLETED
            
            # Complete the future
            if self._response_future and not self._response_future.done():
                self._response_future.set_result(response)
            
            # Schedule termination
            asyncio.create_task(self._schedule_termination())
            
            return True
        
        return False
    
    async def _schedule_termination(self) -> None:
        """Schedule transition to TERMINATED state."""
        # Wait for timer to expire
        if self._request.is_invite:
            await asyncio.sleep(T4)
        else:
            await asyncio.sleep(T4)
        
        self._state = TransactionState.TERMINATED
    
    def cancel(self) -> None:
        """Cancel pending transaction."""
        self._state = TransactionState.TERMINATED
        
        if self._response_future and not self._response_future.done():
            self._response_future.cancel()
        
        if self._retransmit_task:
            self._retransmit_task.cancel()


class ServerTransaction:
    """
    Server transaction (UAS side).
    
    Handles incoming request and response sending.
    
    State machine:
    - TRYING/PROCEEDING -> COMPLETED -> CONFIRMED -> TERMINATED
    
    Example:
        transaction = ServerTransaction(transport, request, client_address)
        await transaction.respond(200, "OK")
    """
    
    __slots__ = (
        "_id",
        "_transport",
        "_request",
        "_state",
        "_client_address",
        "_last_response",
        "_created_at",
    )
    
    def __init__(
        self,
        transport: "UDPTransport",
        request: "SIPRequest",
        client_address: tuple[str, int],
    ):
        # Extract branch from Via header
        via = request.headers.get("via", "")
        branch = ""
        if "branch=" in via:
            start = via.find("branch=") + 7
            end = via.find(";", start)
            if end == -1:
                end = len(via)
            branch = via[start:end]
        
        method = request.method.value if hasattr(request.method, 'value') else str(request.method)
        
        self._id = TransactionId(branch=branch, method=method)
        self._transport = transport
        self._request = request
        self._state = TransactionState.TRYING
        self._client_address = client_address
        self._last_response: bytes | None = None
        self._created_at = time.time()
    
    @property
    def id(self) -> TransactionId:
        """Transaction identifier."""
        return self._id
    
    @property
    def state(self) -> TransactionState:
        """Current transaction state."""
        return self._state
    
    @property
    def request(self) -> "SIPRequest":
        """Original request."""
        return self._request
    
    async def respond(self, response: "SIPResponse") -> None:
        """
        Send response.
        
        Args:
            response: Response to send
        """
        from ..protocol.sip.builder import serialize_response
        
        data = serialize_response(response)
        self._last_response = data
        
        status = response.status_code
        
        # Update state based on response
        if 100 <= status < 200:
            self._state = TransactionState.PROCEEDING
        elif status >= 200:
            self._state = TransactionState.COMPLETED
        
        await self._transport.send(data, self._client_address)
        logger.debug(f"Transaction {self._id}: sent {status} response")
    
    def on_retransmit(self) -> None:
        """Handle request retransmission (resend last response)."""
        if self._last_response and self._state != TransactionState.TERMINATED:
            asyncio.create_task(
                self._transport.send(self._last_response, self._client_address)
            )
    
    def on_ack(self) -> None:
        """Handle ACK for INVITE transaction."""
        if self._request.is_invite and self._state == TransactionState.COMPLETED:
            self._state = TransactionState.CONFIRMED
            asyncio.create_task(self._schedule_termination())
    
    async def _schedule_termination(self) -> None:
        """Schedule transition to TERMINATED state."""
        await asyncio.sleep(T4)
        self._state = TransactionState.TERMINATED


class TransactionManager:
    """
    Manages active transactions.
    
    Routes incoming responses to matching transactions.
    """
    
    __slots__ = ("_client_transactions", "_server_transactions", "_transport")
    
    def __init__(self, transport: "UDPTransport"):
        self._transport = transport
        self._client_transactions: dict[TransactionId, ClientTransaction] = {}
        self._server_transactions: dict[TransactionId, ServerTransaction] = {}
    
    def create_client_transaction(
        self,
        request: "SIPRequest",
        remote_address: tuple[str, int],
    ) -> ClientTransaction:
        """Create and register client transaction."""
        transaction = ClientTransaction(self._transport, request, remote_address)
        self._client_transactions[transaction.id] = transaction
        return transaction
    
    def create_server_transaction(
        self,
        request: "SIPRequest",
        client_address: tuple[str, int],
    ) -> ServerTransaction:
        """Create and register server transaction."""
        transaction = ServerTransaction(self._transport, request, client_address)
        self._server_transactions[transaction.id] = transaction
        return transaction
    
    def match_response(self, response: "SIPResponse") -> ClientTransaction | None:
        """Find transaction matching response."""
        # Extract branch from Via header
        via = response.headers.get("via", "")
        branch = ""
        if "branch=" in via:
            start = via.find("branch=") + 7
            end = via.find(";", start)
            if end == -1:
                end = len(via)
            branch = via[start:end]
        
        # Get method from CSeq
        _, method = response.cseq
        
        trans_id = TransactionId(branch=branch, method=method)
        return self._client_transactions.get(trans_id)
    
    def cleanup_terminated(self) -> None:
        """Remove terminated transactions."""
        # Clean client transactions
        to_remove = [
            tid for tid, trans in self._client_transactions.items()
            if trans.state == TransactionState.TERMINATED
        ]
        for tid in to_remove:
            del self._client_transactions[tid]
        
        # Clean server transactions
        to_remove = [
            tid for tid, trans in self._server_transactions.items()
            if trans.state == TransactionState.TERMINATED
        ]
        for tid in to_remove:
            del self._server_transactions[tid]


