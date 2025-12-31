"""
SIP Message Classes

RFC 3261 compliant SIP message representations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from ...types import NameAddress, SIPMethod, SIPStatusCode, SIPUri

if TYPE_CHECKING:
    from ...protocol.sdp import SDPMessage


@dataclass(slots=True)
class SIPMessage:
    """
    Base SIP message class.
    
    Contains common headers and functionality shared by
    SIPRequest and SIPResponse.
    """
    
    # Standard headers (case-insensitive by spec, stored lowercase)
    headers: dict[str, str] = field(default_factory=dict)
    
    # Parsed body (SDP or other)
    body: bytes | None = None
    sdp: "SDPMessage | None" = None
    
    # Raw message for debugging
    raw: bytes | None = None
    
    # --- Common Header Accessors ---
    
    @property
    def call_id(self) -> str:
        """Call-ID header."""
        return self.headers.get("call-id", "")
    
    @call_id.setter
    def call_id(self, value: str) -> None:
        self.headers["call-id"] = value
    
    @property
    def cseq(self) -> tuple[int, str]:
        """CSeq header as (sequence, method)."""
        cseq = self.headers.get("cseq", "0 UNKNOWN")
        parts = cseq.split(None, 1)
        if len(parts) == 2:
            return int(parts[0]), parts[1]
        return 0, "UNKNOWN"
    
    @cseq.setter
    def cseq(self, value: tuple[int, str]) -> None:
        self.headers["cseq"] = f"{value[0]} {value[1]}"
    
    @property
    def from_header(self) -> str:
        """From header (raw string)."""
        return self.headers.get("from", "")
    
    @from_header.setter
    def from_header(self, value: str) -> None:
        self.headers["from"] = value
    
    @property
    def from_address(self) -> NameAddress:
        """From header parsed as NameAddress."""
        return NameAddress.parse(self.from_header)
    
    @property
    def from_tag(self) -> str | None:
        """From header tag parameter."""
        return self.from_address.parameters.get("tag")
    
    @property
    def to_header(self) -> str:
        """To header (raw string)."""
        return self.headers.get("to", "")
    
    @to_header.setter
    def to_header(self, value: str) -> None:
        self.headers["to"] = value
    
    @property
    def to_address(self) -> NameAddress:
        """To header parsed as NameAddress."""
        return NameAddress.parse(self.to_header)
    
    @property
    def to_tag(self) -> str | None:
        """To header tag parameter."""
        return self.to_address.parameters.get("tag")
    
    @property
    def via(self) -> list[str]:
        """Via headers (list)."""
        via = self.headers.get("via", "")
        if not via:
            return []
        return [v.strip() for v in via.split(",")]
    
    @via.setter
    def via(self, value: list[str]) -> None:
        self.headers["via"] = ", ".join(value)
    
    @property
    def contact(self) -> str:
        """Contact header."""
        return self.headers.get("contact", "")
    
    @contact.setter
    def contact(self, value: str) -> None:
        self.headers["contact"] = value
    
    @property
    def content_type(self) -> str:
        """Content-Type header."""
        return self.headers.get("content-type", "")
    
    @content_type.setter
    def content_type(self, value: str) -> None:
        self.headers["content-type"] = value
    
    @property
    def content_length(self) -> int:
        """Content-Length header."""
        return int(self.headers.get("content-length", "0"))
    
    @content_length.setter
    def content_length(self, value: int) -> None:
        self.headers["content-length"] = str(value)
    
    @property
    def max_forwards(self) -> int:
        """Max-Forwards header."""
        return int(self.headers.get("max-forwards", "70"))
    
    @max_forwards.setter
    def max_forwards(self, value: int) -> None:
        self.headers["max-forwards"] = str(value)
    
    @property
    def user_agent(self) -> str:
        """User-Agent header."""
        return self.headers.get("user-agent", "")
    
    @user_agent.setter
    def user_agent(self, value: str) -> None:
        self.headers["user-agent"] = value
    
    def get_header(self, name: str) -> str | None:
        """Get header by name (case-insensitive)."""
        return self.headers.get(name.lower())
    
    def set_header(self, name: str, value: str) -> None:
        """Set header (stored lowercase)."""
        self.headers[name.lower()] = value
    
    def add_header(self, name: str, value: str) -> None:
        """Add header (appends if exists)."""
        key = name.lower()
        if key in self.headers:
            self.headers[key] += ", " + value
        else:
            self.headers[key] = value


@dataclass(slots=True)
class SIPRequest(SIPMessage):
    """
    SIP Request message.
    
    Examples:
        INVITE sip:user@example.com SIP/2.0
        REGISTER sip:registrar.example.com SIP/2.0
    """
    
    method: SIPMethod | str = SIPMethod.INVITE
    uri: SIPUri | None = None
    version: str = "SIP/2.0"
    
    @property
    def is_invite(self) -> bool:
        return self.method == SIPMethod.INVITE or self.method == "INVITE"
    
    @property
    def is_ack(self) -> bool:
        return self.method == SIPMethod.ACK or self.method == "ACK"
    
    @property
    def is_bye(self) -> bool:
        return self.method == SIPMethod.BYE or self.method == "BYE"
    
    @property
    def is_cancel(self) -> bool:
        return self.method == SIPMethod.CANCEL or self.method == "CANCEL"
    
    @property
    def is_register(self) -> bool:
        return self.method == SIPMethod.REGISTER or self.method == "REGISTER"
    
    @property
    def is_options(self) -> bool:
        return self.method == SIPMethod.OPTIONS or self.method == "OPTIONS"
    
    def __str__(self) -> str:
        method = self.method.value if isinstance(self.method, SIPMethod) else self.method
        return f"SIPRequest({method} {self.uri})"


@dataclass(slots=True)
class SIPResponse(SIPMessage):
    """
    SIP Response message.
    
    Examples:
        SIP/2.0 200 OK
        SIP/2.0 180 Ringing
    """
    
    status_code: int = 200
    reason_phrase: str = "OK"
    version: str = "SIP/2.0"
    
    @property
    def is_provisional(self) -> bool:
        """1xx response."""
        return 100 <= self.status_code < 200
    
    @property
    def is_success(self) -> bool:
        """2xx response."""
        return 200 <= self.status_code < 300
    
    @property
    def is_redirect(self) -> bool:
        """3xx response."""
        return 300 <= self.status_code < 400
    
    @property
    def is_client_error(self) -> bool:
        """4xx response."""
        return 400 <= self.status_code < 500
    
    @property
    def is_server_error(self) -> bool:
        """5xx response."""
        return 500 <= self.status_code < 600
    
    @property
    def is_global_failure(self) -> bool:
        """6xx response."""
        return 600 <= self.status_code < 700
    
    @property
    def is_final(self) -> bool:
        """Final response (2xx-6xx)."""
        return self.status_code >= 200
    
    @property
    def is_error(self) -> bool:
        """Error response (4xx-6xx)."""
        return self.status_code >= 400
    
    def __str__(self) -> str:
        return f"SIPResponse({self.status_code} {self.reason_phrase})"


# Commonly used status code reason phrases
REASON_PHRASES = {
    100: "Trying",
    180: "Ringing",
    181: "Call Is Being Forwarded",
    182: "Queued",
    183: "Session Progress",
    200: "OK",
    202: "Accepted",
    300: "Multiple Choices",
    301: "Moved Permanently",
    302: "Moved Temporarily",
    305: "Use Proxy",
    380: "Alternative Service",
    400: "Bad Request",
    401: "Unauthorized",
    402: "Payment Required",
    403: "Forbidden",
    404: "Not Found",
    405: "Method Not Allowed",
    406: "Not Acceptable",
    407: "Proxy Authentication Required",
    408: "Request Timeout",
    410: "Gone",
    413: "Request Entity Too Large",
    414: "Request-URI Too Long",
    415: "Unsupported Media Type",
    416: "Unsupported URI Scheme",
    420: "Bad Extension",
    421: "Extension Required",
    423: "Interval Too Brief",
    480: "Temporarily Unavailable",
    481: "Call/Transaction Does Not Exist",
    482: "Loop Detected",
    483: "Too Many Hops",
    484: "Address Incomplete",
    485: "Ambiguous",
    486: "Busy Here",
    487: "Request Terminated",
    488: "Not Acceptable Here",
    491: "Request Pending",
    493: "Undecipherable",
    500: "Server Internal Error",
    501: "Not Implemented",
    502: "Bad Gateway",
    503: "Service Unavailable",
    504: "Server Time-out",
    505: "Version Not Supported",
    513: "Message Too Large",
    600: "Busy Everywhere",
    603: "Decline",
    604: "Does Not Exist Anywhere",
    606: "Not Acceptable",
}


def get_reason_phrase(status_code: int) -> str:
    """Get standard reason phrase for status code."""
    return REASON_PHRASES.get(status_code, "Unknown")


