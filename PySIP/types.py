"""
PySIP Type Definitions

Core types, enums, and type aliases used throughout the library.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Literal,
    NamedTuple,
    TypeAlias,
    TypeVar,
)

if TYPE_CHECKING:
    from .call import Call


# =============================================================================
# Type Aliases
# =============================================================================

# Network types
IPAddress: TypeAlias = str
Port: TypeAlias = int
Address: TypeAlias = tuple[IPAddress, Port]

# SIP types
CallID: TypeAlias = str
Tag: TypeAlias = str
Branch: TypeAlias = str
CSeq: TypeAlias = int

# Media types
PayloadType: TypeAlias = int
SSRC: TypeAlias = int
SequenceNumber: TypeAlias = int
Timestamp: TypeAlias = int

# Audio types
AudioData: TypeAlias = bytes
PCMData: TypeAlias = bytes

# Callback types
T = TypeVar("T")
CallHandler: TypeAlias = Callable[["Call"], Awaitable[None]]
DTMFHandler: TypeAlias = Callable[[str], Awaitable[None]]
HangupHandler: TypeAlias = Callable[[str], Awaitable[None]]


# =============================================================================
# Transport Enums
# =============================================================================

class TransportType(str, Enum):
    """SIP transport protocol types."""
    UDP = "UDP"
    TCP = "TCP"
    TLS = "TLS"
    WS = "WS"
    WSS = "WSS"


class TransportState(Enum):
    """Transport connection state."""
    DISCONNECTED = auto()
    CONNECTING = auto()
    CONNECTED = auto()
    CLOSING = auto()
    CLOSED = auto()
    ERROR = auto()


# =============================================================================
# SIP Enums
# =============================================================================

class SIPMethod(str, Enum):
    """SIP request methods."""
    INVITE = "INVITE"
    ACK = "ACK"
    BYE = "BYE"
    CANCEL = "CANCEL"
    REGISTER = "REGISTER"
    OPTIONS = "OPTIONS"
    PRACK = "PRACK"
    SUBSCRIBE = "SUBSCRIBE"
    NOTIFY = "NOTIFY"
    PUBLISH = "PUBLISH"
    INFO = "INFO"
    REFER = "REFER"
    MESSAGE = "MESSAGE"
    UPDATE = "UPDATE"


class SIPStatusCode(IntEnum):
    """Common SIP response status codes."""
    # 1xx - Provisional
    TRYING = 100
    RINGING = 180
    CALL_BEING_FORWARDED = 181
    QUEUED = 182
    SESSION_PROGRESS = 183
    
    # 2xx - Success
    OK = 200
    ACCEPTED = 202
    NO_NOTIFICATION = 204
    
    # 3xx - Redirection
    MULTIPLE_CHOICES = 300
    MOVED_PERMANENTLY = 301
    MOVED_TEMPORARILY = 302
    USE_PROXY = 305
    ALTERNATIVE_SERVICE = 380
    
    # 4xx - Client Error
    BAD_REQUEST = 400
    UNAUTHORIZED = 401
    PAYMENT_REQUIRED = 402
    FORBIDDEN = 403
    NOT_FOUND = 404
    METHOD_NOT_ALLOWED = 405
    NOT_ACCEPTABLE = 406
    PROXY_AUTHENTICATION_REQUIRED = 407
    REQUEST_TIMEOUT = 408
    CONFLICT = 409
    GONE = 410
    REQUEST_ENTITY_TOO_LARGE = 413
    REQUEST_URI_TOO_LONG = 414
    UNSUPPORTED_MEDIA_TYPE = 415
    UNSUPPORTED_URI_SCHEME = 416
    BAD_EXTENSION = 420
    EXTENSION_REQUIRED = 421
    INTERVAL_TOO_BRIEF = 423
    TEMPORARILY_UNAVAILABLE = 480
    CALL_TRANSACTION_DOES_NOT_EXIST = 481
    LOOP_DETECTED = 482
    TOO_MANY_HOPS = 483
    ADDRESS_INCOMPLETE = 484
    AMBIGUOUS = 485
    BUSY_HERE = 486
    REQUEST_TERMINATED = 487
    NOT_ACCEPTABLE_HERE = 488
    REQUEST_PENDING = 491
    UNDECIPHERABLE = 493
    
    # 5xx - Server Error
    SERVER_INTERNAL_ERROR = 500
    NOT_IMPLEMENTED = 501
    BAD_GATEWAY = 502
    SERVICE_UNAVAILABLE = 503
    SERVER_TIMEOUT = 504
    VERSION_NOT_SUPPORTED = 505
    MESSAGE_TOO_LARGE = 513
    
    # 6xx - Global Failure
    BUSY_EVERYWHERE = 600
    DECLINE = 603
    DOES_NOT_EXIST_ANYWHERE = 604
    NOT_ACCEPTABLE_GLOBAL = 606


class DialogState(Enum):
    """SIP dialog state machine states."""
    INIT = auto()
    EARLY = auto()  # 1xx received
    CONFIRMED = auto()  # 2xx received/sent
    TERMINATED = auto()


class TransactionState(Enum):
    """SIP transaction state."""
    INIT = auto()
    CALLING = auto()  # INVITE sent, waiting response
    TRYING = auto()  # Non-INVITE sent, waiting response
    PROCEEDING = auto()  # 1xx received
    COMPLETED = auto()  # Final response received
    CONFIRMED = auto()  # ACK sent (INVITE only)
    TERMINATED = auto()


# =============================================================================
# Call Enums
# =============================================================================

class CallState(Enum):
    """Call lifecycle states."""
    IDLE = auto()
    DIALING = auto()  # INVITE sent
    RINGING = auto()  # 180 received
    EARLY_MEDIA = auto()  # 183 with SDP
    ANSWERING = auto()  # Incoming call being answered
    ACTIVE = auto()  # Call established
    HOLDING = auto()  # Call on hold
    HELD = auto()  # Being held by remote
    TRANSFERRING = auto()  # Transfer in progress
    TERMINATING = auto()  # BYE sent/received
    TERMINATED = auto()  # Call ended


class CallDirection(str, Enum):
    """Call direction."""
    INBOUND = "inbound"
    OUTBOUND = "outbound"


class HangupCause(str, Enum):
    """Call hangup reasons."""
    NORMAL = "normal"
    BUSY = "busy"
    NO_ANSWER = "no_answer"
    REJECTED = "rejected"
    CANCELLED = "cancelled"
    FAILED = "failed"
    TIMEOUT = "timeout"
    ERROR = "error"
    TRANSFERRED = "transferred"


# =============================================================================
# Media Enums
# =============================================================================

class CodecType(IntEnum):
    """RTP payload types for common codecs."""
    PCMU = 0  # G.711 μ-law
    PCMA = 8  # G.711 A-law
    G722 = 9
    G729 = 18
    TELEPHONE_EVENT = 101  # RFC 2833 DTMF


class MediaDirection(str, Enum):
    """SDP media direction."""
    SENDRECV = "sendrecv"
    SENDONLY = "sendonly"
    RECVONLY = "recvonly"
    INACTIVE = "inactive"


class DTMFMode(str, Enum):
    """DTMF transmission mode."""
    RFC2833 = "rfc2833"  # RTP telephone events
    INBAND = "inband"  # Audio tones
    INFO = "info"  # SIP INFO messages


# =============================================================================
# AMD Enums
# =============================================================================

class AMDResultType(str, Enum):
    """Answering machine detection result."""
    HUMAN = "human"
    MACHINE = "machine"
    NOTSURE = "notsure"
    HANGUP = "hangup"
    SILENCE = "silence"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass(slots=True)
class SIPUri:
    """Parsed SIP URI."""
    scheme: Literal["sip", "sips"] = "sip"
    user: str | None = None
    password: str | None = None
    host: str = ""
    port: int | None = None
    parameters: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    
    def __str__(self) -> str:
        result = f"{self.scheme}:"
        if self.user:
            result += self.user
            if self.password:
                result += f":{self.password}"
            result += "@"
        result += self.host
        if self.port:
            result += f":{self.port}"
        if self.parameters:
            for key, value in self.parameters.items():
                if value:
                    result += f";{key}={value}"
                else:
                    result += f";{key}"
        if self.headers:
            headers_str = "&".join(f"{k}={v}" for k, v in self.headers.items())
            result += f"?{headers_str}"
        return result
    
    @classmethod
    def parse(cls, uri_str: str) -> "SIPUri":
        """Parse a SIP URI string."""
        uri = cls()
        
        # Remove angle brackets if present
        uri_str = uri_str.strip().strip("<>")
        
        # Extract scheme
        if uri_str.startswith("sips:"):
            uri.scheme = "sips"
            uri_str = uri_str[5:]
        elif uri_str.startswith("sip:"):
            uri.scheme = "sip"
            uri_str = uri_str[4:]
        
        # Extract headers (after ?)
        if "?" in uri_str:
            uri_str, headers_str = uri_str.split("?", 1)
            for header in headers_str.split("&"):
                if "=" in header:
                    key, value = header.split("=", 1)
                    uri.headers[key] = value
        
        # Extract parameters (after ;)
        if ";" in uri_str:
            parts = uri_str.split(";")
            uri_str = parts[0]
            for param in parts[1:]:
                if "=" in param:
                    key, value = param.split("=", 1)
                    uri.parameters[key] = value
                else:
                    uri.parameters[param] = ""
        
        # Extract user@host:port
        if "@" in uri_str:
            user_part, host_part = uri_str.rsplit("@", 1)
            if ":" in user_part:
                uri.user, uri.password = user_part.split(":", 1)
            else:
                uri.user = user_part
        else:
            host_part = uri_str
        
        # Extract host:port
        if ":" in host_part:
            uri.host, port_str = host_part.rsplit(":", 1)
            try:
                uri.port = int(port_str)
            except ValueError:
                uri.host = host_part
        else:
            uri.host = host_part
        
        return uri


@dataclass(slots=True)
class RTPConfig:
    """RTP session configuration."""
    local_ip: str = "0.0.0.0"
    local_port: int = 0  # 0 = auto-assign
    remote_ip: str | None = None
    remote_port: int | None = None
    payload_type: int = CodecType.PCMU
    clock_rate: int = 8000
    ptime: int = 20  # Packetization time in ms
    ssrc: int | None = None
    rtcp_mux: bool = False  # RFC 5761 - multiplex RTP/RTCP on same port


@dataclass(slots=True)
class MediaConfig:
    """Media session configuration."""
    rtp: RTPConfig = field(default_factory=RTPConfig)
    dtmf_mode: DTMFMode = DTMFMode.RFC2833
    enable_amd: bool = False
    enable_recording: bool = False
    jitter_buffer_size: int = 10  # packets


@dataclass(slots=True)
class ClientConfig:
    """SIP client configuration."""
    username: str = ""
    password: str = ""
    server: str = ""
    port: int = 5060
    transport: TransportType = TransportType.UDP
    local_ip: str | None = None  # Auto-detect if None
    local_port: int = 0  # 0 = auto-assign
    user_agent: str = "PySIP/2.0"
    register_expires: int = 300
    max_concurrent_calls: int = 100
    rtp_port_range: tuple[int, int] = (10000, 20000)
    media: MediaConfig = field(default_factory=MediaConfig)


class NameAddress(NamedTuple):
    """SIP name-addr format (display name + URI)."""
    display_name: str | None
    uri: SIPUri
    parameters: dict[str, str]
    
    def __str__(self) -> str:
        result = ""
        if self.display_name:
            result = f'"{self.display_name}" '
        result += f"<{self.uri}>"
        for key, value in self.parameters.items():
            if value:
                result += f";{key}={value}"
            else:
                result += f";{key}"
        return result
    
    @classmethod
    def parse(cls, value: str) -> "NameAddress":
        """Parse a name-addr string."""
        display_name = None
        parameters: dict[str, str] = {}
        
        value = value.strip()
        
        # Extract display name
        if value.startswith('"'):
            end_quote = value.find('"', 1)
            if end_quote > 0:
                display_name = value[1:end_quote]
                value = value[end_quote + 1:].strip()
        
        # Extract URI between < and >
        if "<" in value and ">" in value:
            start = value.find("<")
            end = value.find(">")
            uri_str = value[start + 1:end]
            params_str = value[end + 1:].strip()
            
            # Parse parameters after >
            if params_str.startswith(";"):
                for param in params_str[1:].split(";"):
                    param = param.strip()
                    if "=" in param:
                        key, val = param.split("=", 1)
                        parameters[key.strip()] = val.strip()
                    elif param:
                        parameters[param] = ""
        else:
            # No angle brackets - URI might be raw
            if ";" in value:
                parts = value.split(";")
                uri_str = parts[0]
                for param in parts[1:]:
                    param = param.strip()
                    if "=" in param:
                        key, val = param.split("=", 1)
                        parameters[key.strip()] = val.strip()
                    elif param:
                        parameters[param] = ""
            else:
                uri_str = value
        
        uri = SIPUri.parse(uri_str)
        return cls(display_name=display_name, uri=uri, parameters=parameters)


