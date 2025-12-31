"""
SIP Dialog State Machine

RFC 3261 compliant dialog handling.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

from ..types import CallID, DialogState, SIPMethod, Tag

if TYPE_CHECKING:
    from ..protocol.sip import SIPRequest, SIPResponse

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class DialogId:
    """
    Unique dialog identifier.
    
    Per RFC 3261, dialog is identified by:
    - Call-ID
    - Local tag (From tag for UAC, To tag for UAS)
    - Remote tag (To tag for UAC, From tag for UAS)
    """
    
    call_id: str
    local_tag: str
    remote_tag: str
    
    def __hash__(self) -> int:
        return hash((self.call_id, self.local_tag, self.remote_tag))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, DialogId):
            return False
        return (
            self.call_id == other.call_id and
            self.local_tag == other.local_tag and
            self.remote_tag == other.remote_tag
        )
    
    def __str__(self) -> str:
        return f"{self.call_id}/{self.local_tag}/{self.remote_tag}"


@dataclass(slots=True)
class Dialog:
    """
    SIP Dialog state.
    
    Tracks a SIP dialog (call leg) from creation to termination.
    
    Attributes:
        id: Dialog identifier
        state: Current dialog state
        local_uri: Local party URI
        remote_uri: Remote party URI
        local_target: Local Contact URI
        remote_target: Remote Contact URI
        route_set: Route headers for requests
        local_cseq: Local CSeq counter
        remote_cseq: Last received remote CSeq
        secure: Whether dialog uses TLS
    """
    
    id: DialogId
    state: DialogState = DialogState.INIT
    
    # URIs
    local_uri: str = ""
    remote_uri: str = ""
    local_target: str = ""  # Local Contact
    remote_target: str = ""  # Remote Contact
    
    # Route set
    route_set: list[str] = field(default_factory=list)
    
    # Sequence numbers
    local_cseq: int = 1
    remote_cseq: int = 0
    
    # Security
    secure: bool = False
    
    # Timestamps
    created_at: float = field(default_factory=time.time)
    confirmed_at: float | None = None
    
    # Callbacks
    _on_state_change: Callable[[DialogState], None] | None = field(
        default=None, repr=False
    )
    
    def next_cseq(self) -> int:
        """Get next local CSeq and increment."""
        cseq = self.local_cseq
        self.local_cseq += 1
        return cseq
    
    def validate_cseq(self, cseq: int) -> bool:
        """
        Validate incoming CSeq.
        
        Returns True if CSeq is valid (greater than last seen).
        """
        if cseq <= self.remote_cseq:
            return False
        self.remote_cseq = cseq
        return True
    
    def set_state(self, state: DialogState) -> None:
        """Update dialog state."""
        if self.state != state:
            old_state = self.state
            self.state = state
            
            if state == DialogState.CONFIRMED:
                self.confirmed_at = time.time()
            
            logger.debug(f"Dialog {self.id} state: {old_state.name} -> {state.name}")
            
            if self._on_state_change:
                self._on_state_change(state)
    
    def on_state_change(self, callback: Callable[[DialogState], None]) -> None:
        """Set state change callback."""
        self._on_state_change = callback


class DialogStateMachine:
    """
    Dialog state machine manager.
    
    Handles dialog lifecycle based on SIP messages.
    
    Example:
        dialog = Dialog(id=dialog_id)
        machine = DialogStateMachine(dialog)
        
        # Process incoming response
        machine.on_response(response)
        
        # Check state
        if dialog.state == DialogState.CONFIRMED:
            print("Call connected!")
    """
    
    __slots__ = ("_dialog",)
    
    def __init__(self, dialog: Dialog):
        self._dialog = dialog
    
    @property
    def dialog(self) -> Dialog:
        """Get managed dialog."""
        return self._dialog
    
    @property
    def state(self) -> DialogState:
        """Current dialog state."""
        return self._dialog.state
    
    def on_invite_sent(self) -> None:
        """Handle outgoing INVITE."""
        if self._dialog.state == DialogState.INIT:
            # Stay in INIT until we get a response
            pass
    
    def on_response(self, response: "SIPResponse") -> None:
        """
        Process incoming response.
        
        Updates dialog state based on response code.
        """
        status = response.status_code
        
        # Extract remote tag from To header if not yet set
        if not self._dialog.id.remote_tag:
            to_tag = response.to_tag
            if to_tag:
                self._dialog.id = DialogId(
                    call_id=self._dialog.id.call_id,
                    local_tag=self._dialog.id.local_tag,
                    remote_tag=to_tag,
                )
        
        # Update remote target from Contact
        contact = response.contact
        if contact:
            # Extract URI from Contact
            if "<" in contact:
                start = contact.find("<") + 1
                end = contact.find(">")
                self._dialog.remote_target = contact[start:end]
            else:
                self._dialog.remote_target = contact.split(";")[0].strip()
        
        # State transitions
        current = self._dialog.state
        
        if current == DialogState.INIT:
            if 100 <= status < 200:
                self._dialog.set_state(DialogState.EARLY)
            elif 200 <= status < 300:
                self._dialog.set_state(DialogState.CONFIRMED)
            elif status >= 300:
                self._dialog.set_state(DialogState.TERMINATED)
        
        elif current == DialogState.EARLY:
            if 200 <= status < 300:
                self._dialog.set_state(DialogState.CONFIRMED)
            elif status >= 300:
                self._dialog.set_state(DialogState.TERMINATED)
        
        elif current == DialogState.CONFIRMED:
            # BYE or error terminates
            pass
    
    def on_request(self, request: "SIPRequest") -> None:
        """
        Process incoming request.
        
        Updates dialog state based on request method.
        """
        method = request.method
        if isinstance(method, SIPMethod):
            method = method.value
        
        # Validate CSeq
        cseq_num, _ = request.cseq
        if not self._dialog.validate_cseq(cseq_num):
            logger.warning(f"Invalid CSeq {cseq_num} in dialog {self._dialog.id}")
            return
        
        if method == "BYE":
            self._dialog.set_state(DialogState.TERMINATED)
        
        elif method == "INVITE":
            # Re-INVITE (hold, update, etc.)
            pass
        
        elif method == "CANCEL":
            if self._dialog.state in (DialogState.INIT, DialogState.EARLY):
                self._dialog.set_state(DialogState.TERMINATED)
    
    def terminate(self) -> None:
        """Terminate dialog."""
        self._dialog.set_state(DialogState.TERMINATED)


def create_dialog_from_request(
    request: "SIPRequest",
    local_tag: str,
    is_uac: bool = True,
) -> Dialog:
    """
    Create dialog from initial request.
    
    Args:
        request: INVITE or other dialog-creating request
        local_tag: Local tag to use
        is_uac: True if we're the UAC (caller)
        
    Returns:
        New Dialog instance
    """
    from_addr = request.from_address
    to_addr = request.to_address
    
    if is_uac:
        # We sent the request
        return Dialog(
            id=DialogId(
                call_id=request.call_id,
                local_tag=local_tag,
                remote_tag=request.to_tag or "",
            ),
            local_uri=str(from_addr.uri),
            remote_uri=str(to_addr.uri),
            local_cseq=request.cseq[0] + 1,
        )
    else:
        # We received the request
        return Dialog(
            id=DialogId(
                call_id=request.call_id,
                local_tag=local_tag,
                remote_tag=request.from_tag or "",
            ),
            local_uri=str(to_addr.uri),
            remote_uri=str(from_addr.uri),
            remote_cseq=request.cseq[0],
        )


def create_dialog_from_response(
    request: "SIPRequest",
    response: "SIPResponse",
) -> Dialog:
    """
    Create dialog from request/response pair.
    
    Args:
        request: Original request
        response: 2xx response establishing dialog
        
    Returns:
        New Dialog instance
    """
    from_addr = request.from_address
    to_addr = request.to_address
    
    # Extract Contact from response
    remote_target = ""
    contact = response.contact
    if contact:
        if "<" in contact:
            start = contact.find("<") + 1
            end = contact.find(">")
            remote_target = contact[start:end]
        else:
            remote_target = contact.split(";")[0].strip()
    
    return Dialog(
        id=DialogId(
            call_id=request.call_id,
            local_tag=request.from_tag or "",
            remote_tag=response.to_tag or "",
        ),
        state=DialogState.CONFIRMED,
        local_uri=str(from_addr.uri),
        remote_uri=str(to_addr.uri),
        remote_target=remote_target,
        local_cseq=request.cseq[0] + 1,
    )


