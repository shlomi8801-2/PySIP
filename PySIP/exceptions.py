"""
PySIP Exception Classes

All exceptions raised by the PySIP library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import CallState, SIPStatusCode


class PySIPError(Exception):
    """Base exception for all PySIP errors."""
    
    def __init__(self, message: str = "", *args, **kwargs):
        self.message = message
        super().__init__(message, *args, **kwargs)


# =============================================================================
# Transport Errors
# =============================================================================

class TransportError(PySIPError):
    """Base class for transport-related errors."""
    pass


class ConnectionError(TransportError):
    """Failed to establish connection."""
    pass


class ConnectionTimeoutError(TransportError):
    """Connection timed out."""
    pass


class ConnectionClosedError(TransportError):
    """Connection was closed unexpectedly."""
    pass


class SendError(TransportError):
    """Failed to send data."""
    pass


class ReceiveError(TransportError):
    """Failed to receive data."""
    pass


class BindError(TransportError):
    """Failed to bind to address/port."""
    
    def __init__(self, address: str, port: int, message: str = ""):
        self.address = address
        self.port = port
        super().__init__(message or f"Failed to bind to {address}:{port}")


# =============================================================================
# Protocol Errors
# =============================================================================

class ProtocolError(PySIPError):
    """Base class for protocol-related errors."""
    pass


class SIPParseError(ProtocolError):
    """Failed to parse SIP message."""
    
    def __init__(self, message: str = "", raw_data: bytes | None = None):
        self.raw_data = raw_data
        super().__init__(message)


class SDPParseError(ProtocolError):
    """Failed to parse SDP message."""
    pass


class RTPParseError(ProtocolError):
    """Failed to parse RTP packet."""
    pass


class InvalidMessageError(ProtocolError):
    """Invalid or malformed message."""
    pass


# =============================================================================
# Authentication Errors
# =============================================================================

class AuthenticationError(PySIPError):
    """Base class for authentication errors."""
    pass


class AuthenticationRequired(AuthenticationError):
    """Authentication is required but not provided."""
    
    def __init__(
        self,
        realm: str | None = None,
        nonce: str | None = None,
        message: str = "Authentication required",
    ):
        self.realm = realm
        self.nonce = nonce
        super().__init__(message)


class AuthenticationFailed(AuthenticationError):
    """Authentication credentials were rejected."""
    pass


class RegistrationError(AuthenticationError):
    """Failed to register with SIP server."""
    
    def __init__(
        self,
        status_code: int | None = None,
        reason: str | None = None,
        message: str = "Registration failed",
    ):
        self.status_code = status_code
        self.reason = reason
        super().__init__(message)


# =============================================================================
# Call Errors
# =============================================================================

class CallError(PySIPError):
    """Base class for call-related errors."""
    pass


class CallNotFoundError(CallError):
    """Call with specified ID not found."""
    
    def __init__(self, call_id: str):
        self.call_id = call_id
        super().__init__(f"Call not found: {call_id}")


class CallStateError(CallError):
    """Invalid operation for current call state."""
    
    def __init__(
        self,
        operation: str,
        current_state: "CallState",
        message: str = "",
    ):
        self.operation = operation
        self.current_state = current_state
        super().__init__(
            message or f"Cannot {operation} in state {current_state.name}"
        )


class CallRejectedError(CallError):
    """Call was rejected by remote party."""
    
    def __init__(
        self,
        status_code: "SIPStatusCode | int",
        reason: str | None = None,
    ):
        self.status_code = status_code
        self.reason = reason
        super().__init__(f"Call rejected: {status_code} {reason or ''}")


class CallFailedError(CallError):
    """Call failed to connect."""
    
    def __init__(
        self,
        status_code: int | None = None,
        reason: str | None = None,
        message: str = "Call failed",
    ):
        self.status_code = status_code
        self.reason = reason
        super().__init__(message)


class CallTimeoutError(CallError):
    """Call operation timed out."""
    pass


class TransferError(CallError):
    """Call transfer failed."""
    pass


# =============================================================================
# Media Errors
# =============================================================================

class MediaError(PySIPError):
    """Base class for media-related errors."""
    pass


class CodecError(MediaError):
    """Codec encoding/decoding error."""
    pass


class CodecNotSupportedError(MediaError):
    """Requested codec is not supported."""
    
    def __init__(self, codec_name: str):
        self.codec_name = codec_name
        super().__init__(f"Codec not supported: {codec_name}")


class RTPError(MediaError):
    """RTP transport error."""
    pass


class JitterBufferError(MediaError):
    """Jitter buffer error."""
    pass


class AudioStreamError(MediaError):
    """Audio stream error."""
    pass


class AudioFileError(MediaError):
    """Failed to load or process audio file."""
    
    def __init__(self, filepath: str, message: str = ""):
        self.filepath = filepath
        super().__init__(message or f"Audio file error: {filepath}")


# =============================================================================
# Feature Errors
# =============================================================================

class TTSError(PySIPError):
    """Text-to-speech error."""
    pass


class AMDError(PySIPError):
    """Answering machine detection error."""
    pass


class DTMFError(PySIPError):
    """DTMF detection/generation error."""
    pass


class RecordingError(PySIPError):
    """Recording error."""
    pass


# =============================================================================
# Configuration Errors
# =============================================================================

class ConfigurationError(PySIPError):
    """Invalid configuration."""
    pass


class InvalidURIError(ConfigurationError):
    """Invalid SIP URI."""
    
    def __init__(self, uri: str, message: str = ""):
        self.uri = uri
        super().__init__(message or f"Invalid URI: {uri}")


# =============================================================================
# Resource Errors
# =============================================================================

class ResourceError(PySIPError):
    """Resource-related error."""
    pass


class PortExhaustedError(ResourceError):
    """No available ports in the configured range."""
    
    def __init__(self, port_range: tuple[int, int]):
        self.port_range = port_range
        super().__init__(
            f"No available ports in range {port_range[0]}-{port_range[1]}"
        )


class MaxCallsReachedError(ResourceError):
    """Maximum concurrent calls limit reached."""
    
    def __init__(self, max_calls: int):
        self.max_calls = max_calls
        super().__init__(f"Maximum concurrent calls reached: {max_calls}")


# =============================================================================
# Timeout Errors  
# =============================================================================

class TimeoutError(PySIPError):
    """Operation timed out."""
    pass


class TransactionTimeoutError(TimeoutError):
    """SIP transaction timed out."""
    pass


class ResponseTimeoutError(TimeoutError):
    """Waiting for response timed out."""
    pass


class GatherTimeoutError(TimeoutError):
    """DTMF gather operation timed out."""
    pass
