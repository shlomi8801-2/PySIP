"""
PySIP - High-Performance Async SIP Client

A modern, asyncio-based SIP/VoIP library for Python.

Example (simple - context manager):
    from PySIP import SIPClient
    
    async with SIPClient(
        username="alice",
        password="secret",
        server="sip.example.com",
    ) as client:
        await client.register()
        
        # dial() returns a Call that auto-connects and auto-hangups
        async with client.dial("sip:bob@example.com") as call:
            await call.say("Hello!")
            result = await call.gather(max_digits=4, timeout=10)
            print(f"Got digits: {result.digits}")
            # Auto-hangup when exiting

Example (advanced - configure before connecting):
    from PySIP import SIPClient
    
    async with SIPClient(
        username="alice",
        password="secret",
        server="sip.example.com",
    ) as client:
        await client.register()
        
        # create_call() returns unconfigured Call for advanced setup
        call = client.create_call("sip:bob@example.com")
        call.set_caller_id("sip:support@company.com")
        call.set_display_name("Support Line")
        call.add_header("X-Campaign-ID", "promo123")
        call.set_codecs(["pcmu", "pcma"])
        call.on("ringing", lambda: print("Ringing..."))
        
        await call.connect()  # Now connect
        await call.say("Hello!")
        await call.hangup()
"""

__version__ = "2.0.0"
__author__ = "PySIP Contributors"
__license__ = "MIT"

# Core client
from .client import SIPClient, create_client
from .call import Call, GatherResult

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
    MediaDirection,
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
    "GatherResult",
    
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
    "MediaDirection",
    
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
