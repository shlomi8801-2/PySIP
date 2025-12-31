"""
SIP Message Builder

Builds SIP messages with proper header formatting.
"""

from __future__ import annotations

import hashlib
import random
import string
import time
from typing import TYPE_CHECKING

from ...types import NameAddress, SIPMethod, SIPUri
from .message import SIPRequest, SIPResponse, get_reason_phrase

if TYPE_CHECKING:
    from ...protocol.sdp import SDPMessage


# RFC 3261 compliant Allow header - methods this UA supports
ALLOW_METHODS = "INVITE, ACK, BYE, CANCEL, OPTIONS, INFO, REFER, NOTIFY"

# Supported extensions
SUPPORTED_EXTENSIONS = "replaces, timer"


class SIPBuilder:
    """
    SIP message builder.
    
    Provides factory methods and fluent API for building SIP messages.
    
    Example:
        builder = SIPBuilder(
            local_ip="192.168.1.100",
            local_port=5060,
            user_agent="PySIP/2.0"
        )
        
        request = builder.invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
        )
        
        response = builder.response(
            request=request,
            status_code=200,
        )
    """
    
    __slots__ = (
        "_local_ip",
        "_local_port",
        "_user_agent",
        "_cseq_counter",
    )
    
    def __init__(
        self,
        local_ip: str = "0.0.0.0",
        local_port: int = 5060,
        user_agent: str = "PySIP/2.0",
    ):
        self._local_ip = local_ip
        self._local_port = local_port
        self._user_agent = user_agent
        self._cseq_counter = 1
    
    @staticmethod
    def generate_call_id(domain: str | None = None) -> str:
        """Generate unique Call-ID."""
        unique = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        if domain:
            return f"{unique}@{domain}"
        return unique
    
    @staticmethod
    def generate_tag() -> str:
        """Generate unique tag for From/To headers."""
        return "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    
    @staticmethod
    def generate_branch() -> str:
        """Generate unique branch parameter for Via header."""
        # Must start with "z9hG4bK" per RFC 3261
        unique = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        return f"z9hG4bK{unique}"
    
    def _next_cseq(self) -> int:
        """Get next CSeq number."""
        cseq = self._cseq_counter
        self._cseq_counter += 1
        return cseq
    
    def _build_via(self, branch: str | None = None) -> str:
        """Build Via header."""
        branch = branch or self.generate_branch()
        return f"SIP/2.0/UDP {self._local_ip}:{self._local_port};branch={branch};rport"
    
    def request(
        self,
        method: SIPMethod | str,
        uri: SIPUri | str,
        *,
        from_uri: SIPUri | str,
        to_uri: SIPUri | str,
        from_display_name: str | None = None,
        to_display_name: str | None = None,
        call_id: str | None = None,
        cseq: int | None = None,
        from_tag: str | None = None,
        to_tag: str | None = None,
        via_branch: str | None = None,
        contact_uri: SIPUri | str | None = None,
        max_forwards: int = 70,
        body: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> SIPRequest:
        """
        Build a SIP request.
        
        Args:
            method: SIP method
            uri: Request-URI
            from_uri: From header URI
            to_uri: To header URI
            from_display_name: From display name
            to_display_name: To display name
            call_id: Call-ID (generated if not provided)
            cseq: CSeq number (auto-incremented if not provided)
            from_tag: From tag (generated if not provided)
            to_tag: To tag (None for new dialogs)
            via_branch: Via branch (generated if not provided)
            contact_uri: Contact URI
            max_forwards: Max-Forwards value
            body: Message body
            content_type: Content-Type for body
            extra_headers: Additional headers
            
        Returns:
            Built SIPRequest
        """
        # Parse URIs if strings
        if isinstance(uri, str):
            uri = SIPUri.parse(uri)
        if isinstance(from_uri, str):
            from_uri = SIPUri.parse(from_uri)
        if isinstance(to_uri, str):
            to_uri = SIPUri.parse(to_uri)
        if contact_uri and isinstance(contact_uri, str):
            contact_uri = SIPUri.parse(contact_uri)
        
        # Generate required values
        call_id = call_id or self.generate_call_id(self._local_ip)
        from_tag = from_tag or self.generate_tag()
        cseq = cseq or self._next_cseq()
        method_str = method.value if isinstance(method, SIPMethod) else method
        
        # Build headers
        headers: dict[str, str] = {}
        
        # Via
        headers["via"] = self._build_via(via_branch)
        
        # Max-Forwards
        headers["max-forwards"] = str(max_forwards)
        
        # From with tag
        from_str = ""
        if from_display_name:
            from_str = f'"{from_display_name}" '
        from_str += f"<{from_uri}>;tag={from_tag}"
        headers["from"] = from_str
        
        # To (with tag if provided)
        to_str = ""
        if to_display_name:
            to_str = f'"{to_display_name}" '
        to_str += f"<{to_uri}>"
        if to_tag:
            to_str += f";tag={to_tag}"
        headers["to"] = to_str
        
        # Call-ID
        headers["call-id"] = call_id
        
        # CSeq
        headers["cseq"] = f"{cseq} {method_str}"
        
        # Contact
        if contact_uri:
            headers["contact"] = f"<{contact_uri}>"
        elif method_str in ("INVITE", "REGISTER", "SUBSCRIBE"):
            contact = f"sip:{from_uri.user}@{self._local_ip}:{self._local_port}"
            headers["contact"] = f"<{contact}>"
        
        # Allow header - RFC 3261 Section 20.5
        # Include in INVITE, OPTIONS, and 405/200 responses
        if method_str in ("INVITE", "OPTIONS", "REGISTER"):
            headers["allow"] = ALLOW_METHODS
        
        # Supported header - RFC 3261 Section 20.37
        if method_str in ("INVITE", "OPTIONS", "REGISTER", "UPDATE"):
            headers["supported"] = SUPPORTED_EXTENSIONS
        
        # User-Agent
        headers["user-agent"] = self._user_agent
        
        # Body handling
        if body:
            headers["content-type"] = content_type or "application/sdp"
            headers["content-length"] = str(len(body))
        else:
            headers["content-length"] = "0"
        
        # Extra headers
        if extra_headers:
            for name, value in extra_headers.items():
                headers[name.lower()] = value
        
        return SIPRequest(
            method=method if isinstance(method, SIPMethod) else method_str,
            uri=uri,
            headers=headers,
            body=body,
        )
    
    def response(
        self,
        request: SIPRequest,
        status_code: int,
        reason_phrase: str | None = None,
        *,
        to_tag: str | None = None,
        contact_uri: SIPUri | str | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> SIPResponse:
        """
        Build a SIP response to a request.
        
        Args:
            request: Request to respond to
            status_code: Response status code
            reason_phrase: Custom reason phrase (default: standard phrase)
            to_tag: To tag (generated for 1xx-2xx if not provided)
            contact_uri: Contact URI
            body: Message body
            content_type: Content-Type for body
            extra_headers: Additional headers
            
        Returns:
            Built SIPResponse
        """
        reason_phrase = reason_phrase or get_reason_phrase(status_code)
        
        # Copy essential headers from request
        headers: dict[str, str] = {}
        
        # Via - copy from request
        if "via" in request.headers:
            headers["via"] = request.headers["via"]
        
        # From - copy from request
        if "from" in request.headers:
            headers["from"] = request.headers["from"]
        
        # To - copy and add tag for 1xx-2xx
        if "to" in request.headers:
            to_header = request.headers["to"]
            if status_code >= 100 and status_code < 300:
                if ";tag=" not in to_header.lower():
                    to_tag = to_tag or self.generate_tag()
                    to_header += f";tag={to_tag}"
            headers["to"] = to_header
        
        # Call-ID - copy from request
        if "call-id" in request.headers:
            headers["call-id"] = request.headers["call-id"]
        
        # CSeq - copy from request
        if "cseq" in request.headers:
            headers["cseq"] = request.headers["cseq"]
        
        # Contact for 1xx-2xx responses to INVITE
        if 100 <= status_code < 300 and request.is_invite:
            if contact_uri:
                if isinstance(contact_uri, str):
                    headers["contact"] = f"<{contact_uri}>"
                else:
                    headers["contact"] = f"<{contact_uri}>"
            else:
                from_addr = request.from_address
                if from_addr.uri.user:
                    contact = f"sip:{from_addr.uri.user}@{self._local_ip}:{self._local_port}"
                else:
                    contact = f"sip:{self._local_ip}:{self._local_port}"
                headers["contact"] = f"<{contact}>"
        
        # Allow header in responses - RFC 3261 Section 20.5
        # Include in 200 OK to INVITE, OPTIONS, and 405 Method Not Allowed
        if request.is_invite and 200 <= status_code < 300:
            headers["allow"] = ALLOW_METHODS
        elif request.is_options:
            headers["allow"] = ALLOW_METHODS
        elif status_code == 405:
            headers["allow"] = ALLOW_METHODS
        
        # Supported header in responses
        if request.is_invite and 200 <= status_code < 300:
            headers["supported"] = SUPPORTED_EXTENSIONS
        
        # User-Agent
        headers["user-agent"] = self._user_agent
        
        # Body handling
        if body:
            headers["content-type"] = content_type or "application/sdp"
            headers["content-length"] = str(len(body))
        else:
            headers["content-length"] = "0"
        
        # Extra headers
        if extra_headers:
            for name, value in extra_headers.items():
                headers[name.lower()] = value
        
        return SIPResponse(
            status_code=status_code,
            reason_phrase=reason_phrase,
            headers=headers,
            body=body,
        )
    
    # === Convenience Methods ===
    
    def invite(
        self,
        from_uri: SIPUri | str,
        to_uri: SIPUri | str,
        sdp: bytes | None = None,
        **kwargs,
    ) -> SIPRequest:
        """Build INVITE request."""
        return self.request(
            method=SIPMethod.INVITE,
            uri=to_uri if isinstance(to_uri, SIPUri) else SIPUri.parse(to_uri),
            from_uri=from_uri,
            to_uri=to_uri,
            body=sdp,
            content_type="application/sdp" if sdp else None,
            **kwargs,
        )
    
    def ack(
        self,
        invite: SIPRequest,
        response: SIPResponse,
        **kwargs,
    ) -> SIPRequest:
        """Build ACK for INVITE transaction."""
        # ACK uses same Call-ID, From, and CSeq number
        cseq_num = invite.cseq[0]
        
        return self.request(
            method=SIPMethod.ACK,
            uri=invite.uri,
            from_uri=invite.from_address.uri,
            to_uri=invite.to_address.uri,
            call_id=invite.call_id,
            cseq=cseq_num,
            from_tag=invite.from_tag,
            to_tag=response.to_tag,
            **kwargs,
        )
    
    def bye(
        self,
        dialog_call_id: str,
        from_uri: SIPUri | str,
        to_uri: SIPUri | str,
        from_tag: str,
        to_tag: str,
        **kwargs,
    ) -> SIPRequest:
        """Build BYE request."""
        return self.request(
            method=SIPMethod.BYE,
            uri=to_uri if isinstance(to_uri, SIPUri) else SIPUri.parse(to_uri),
            from_uri=from_uri,
            to_uri=to_uri,
            call_id=dialog_call_id,
            from_tag=from_tag,
            to_tag=to_tag,
            **kwargs,
        )
    
    def cancel(self, invite: SIPRequest, **kwargs) -> SIPRequest:
        """Build CANCEL for pending INVITE."""
        # CANCEL uses same branch as INVITE
        via = invite.headers.get("via", "")
        branch = None
        if "branch=" in via:
            start = via.find("branch=") + 7
            end = via.find(";", start)
            if end == -1:
                end = len(via)
            branch = via[start:end]
        
        return self.request(
            method=SIPMethod.CANCEL,
            uri=invite.uri,
            from_uri=invite.from_address.uri,
            to_uri=invite.to_address.uri,
            call_id=invite.call_id,
            cseq=invite.cseq[0],
            from_tag=invite.from_tag,
            via_branch=branch,
            **kwargs,
        )
    
    def register(
        self,
        server_uri: SIPUri | str,
        from_uri: SIPUri | str,
        contact_uri: SIPUri | str | None = None,
        expires: int = 3600,
        **kwargs,
    ) -> SIPRequest:
        """Build REGISTER request."""
        extra_headers = kwargs.pop("extra_headers", {}) or {}
        extra_headers["expires"] = str(expires)
        
        return self.request(
            method=SIPMethod.REGISTER,
            uri=server_uri if isinstance(server_uri, SIPUri) else SIPUri.parse(server_uri),
            from_uri=from_uri,
            to_uri=from_uri,  # To = From for REGISTER
            contact_uri=contact_uri,
            extra_headers=extra_headers,
            **kwargs,
        )
    
    def options(
        self,
        uri: SIPUri | str,
        from_uri: SIPUri | str,
        **kwargs,
    ) -> SIPRequest:
        """Build OPTIONS request."""
        return self.request(
            method=SIPMethod.OPTIONS,
            uri=uri if isinstance(uri, SIPUri) else SIPUri.parse(uri),
            from_uri=from_uri,
            to_uri=uri,
            **kwargs,
        )


def serialize_request(request: SIPRequest) -> bytes:
    """
    Serialize SIP request to bytes.
    
    Args:
        request: SIPRequest to serialize
        
    Returns:
        Wire-format bytes
    """
    method = request.method.value if isinstance(request.method, SIPMethod) else request.method
    lines = [f"{method} {request.uri} {request.version}"]
    
    # Add headers
    for name, value in request.headers.items():
        # Convert to proper case (e.g., "call-id" -> "Call-ID")
        proper_name = "-".join(part.capitalize() for part in name.split("-"))
        lines.append(f"{proper_name}: {value}")
    
    # Join with CRLF
    message = "\r\n".join(lines) + "\r\n\r\n"
    
    # Add body if present
    if request.body:
        return message.encode("utf-8") + request.body
    
    return message.encode("utf-8")


def serialize_response(response: SIPResponse) -> bytes:
    """
    Serialize SIP response to bytes.
    
    Args:
        response: SIPResponse to serialize
        
    Returns:
        Wire-format bytes
    """
    lines = [f"{response.version} {response.status_code} {response.reason_phrase}"]
    
    # Add headers
    for name, value in response.headers.items():
        # Convert to proper case
        proper_name = "-".join(part.capitalize() for part in name.split("-"))
        lines.append(f"{proper_name}: {value}")
    
    # Join with CRLF
    message = "\r\n".join(lines) + "\r\n\r\n"
    
    # Add body if present
    if response.body:
        return message.encode("utf-8") + response.body
    
    return message.encode("utf-8")


