"""
PySIP - High-Performance Async SIP Client

A modern, asyncio-based SIP/VoIP library for Python.

Example:
    from PySIP import SIPClient
    
    async with SIPClient(
        username="alice",
        password="secret",
        server="sip.example.com",
    ) as client:
        await client.register()
        
        call = client.make_call("sip:bob@example.com")
        await call.start()
        await call.say("Hello!")
        await call.hangup()
"""

__version__ = "2.0.0"
__author__ = "PySIP Contributors"
__license__ = "MIT"

# Core client
from .client import SIPClient, create_client
from .call import Call

# Types and enums
from .types import (
    CallState,
    CallDirection,
    DialogState,
    HangupCause,
    TransportType,
    SIPMethod,
    SIPStatusCode,
    CodecType,
    DTMFMode,
    AMDResultType,
    # Config classes
    ClientConfig,
    MediaConfig,
    RTPConfig,
)

# Exceptions
from .exceptions import (
    PySIPError,
    TransportError,
    ProtocolError,
    AuthenticationError,
    RegistrationError,
    CallError,
    CallRejectedError,
    CallFailedError,
    CallTimeoutError,
    CallStateError,
    MediaError,
    CodecError,
    TTSError,
    AMDError,
    DTMFError,
    RecordingError,
)

# Features
from .features import (
    TTSEngine,
    EdgeTTSEngine,
    AMDDetector,
    AMDResult,
    DTMFDetector,
    DTMFGenerator,
    CallRecorder,
)

# Media
from .media import (
    AudioStream,
    JitterBuffer,
    PCMUCodec,
    PCMACodec,
)

# Protocol (advanced usage)
from .protocol import (
    SIPMessage,
    SIPRequest,
    SIPResponse,
    SDPMessage,
    RTPPacket,
)

__all__ = [
    # Version info
    "__version__",
    "__author__",
    "__license__",
    
    # Core
    "SIPClient",
    "create_client",
    "Call",
    
    # Enums
    "CallState",
    "CallDirection",
    "DialogState",
    "HangupCause",
    "TransportType",
    "SIPMethod",
    "SIPStatusCode",
    "CodecType",
    "DTMFMode",
    "AMDResultType",
    
    # Config
    "ClientConfig",
    "MediaConfig",
    "RTPConfig",
    
    # Exceptions
    "PySIPError",
    "TransportError",
    "ProtocolError",
    "AuthenticationError",
    "RegistrationError",
    "CallError",
    "CallRejectedError",
    "CallFailedError",
    "CallTimeoutError",
    "CallStateError",
    "MediaError",
    "CodecError",
    "TTSError",
    "AMDError",
    "DTMFError",
    "RecordingError",
    
    # Features
    "TTSEngine",
    "EdgeTTSEngine",
    "AMDDetector",
    "AMDResult",
    "DTMFDetector",
    "DTMFGenerator",
    "CallRecorder",
    
    # Media
    "AudioStream",
    "JitterBuffer",
    "PCMUCodec",
    "PCMACodec",
    
    # Protocol
    "SIPMessage",
    "SIPRequest",
    "SIPResponse",
    "SDPMessage",
    "RTPPacket",
]
