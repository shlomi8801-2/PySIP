<p align="center">
  <img src="https://raw.githubusercontent.com/moha-abdi/pysip/main/.github/images/banner.png" alt="PySIP Logo" style="display: block; margin: 0 auto; width: 50%;">
</p>
<p align="center">
  <b>High-Performance Async Python SIP/VoIP Library</b>
</p>

<p align="center">
  <a href="#features">Features</a> •
  <a href="#installation">Installation</a> •
  <a href="#quick-start">Quick Start</a> •
  <a href="#documentation">Documentation</a> •
  <a href="#contributing">Contributing</a>
</p>

---

**PySIP v2** is a complete rewrite of the PySIP library, featuring a high-performance async architecture built on Python's `asyncio`. Designed for building scalable VoIP applications, call centers, IVR systems, and SIP-based automation.

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Pure Async Architecture** | Built on `asyncio` with zero threads for RTP handling |
| **High Performance** | 100+ concurrent calls on standard hardware |
| **RFC Compliant** | SIP (RFC 3261), SDP (RFC 4566), RTP (RFC 3550) |
| **G.711 Codecs** | Numpy-optimized PCMU/PCMA with lookup tables |
| **Text-to-Speech** | Built-in Edge TTS integration |
| **DTMF Support** | RFC 2833 events + inband detection |
| **AMD** | Answering Machine Detection |
| **Call Recording** | Async call recording to WAV |
| **uvloop Support** | Optional 2-3x performance boost |

## 📦 Installation

### From PyPI

```bash
pip install PySIPio
```

### From Source

```bash
git clone https://github.com/moha-abdi/PySIP.git
cd PySIP
pip install -e .
```

### With Optional Dependencies

```bash
# With uvloop for better performance (Linux/macOS)
pip install PySIPio[uvloop]

# With development tools
pip install PySIPio[dev]

# Everything
pip install PySIPio[all]
```

## 🚀 Quick Start

### Basic Outbound Call

```python
import asyncio
from PySIP import SIPClient

async def main():
    # Create and start client
    async with SIPClient(
        username="your_username",
        password="your_password",
        server="sip.example.com",
    ) as client:
        # Register with server
        await client.register()
        
        # Make a call using context manager (recommended)
        async with client.dial("1234567890") as call:
            # Play TTS message
            await call.say("Hello! This is a test call from PySIP.")
            
            # Gather DTMF input
            result = await call.gather(max_digits=4, timeout=10)
            print(f"User pressed: {result.digits}")
            print(f"Terminated by: {result.terminated_by}")
            # Auto-hangup when exiting context

asyncio.run(main())
```

### Advanced Call Configuration

```python
import asyncio
from PySIP import SIPClient

async def main():
    async with SIPClient(
        username="your_username",
        password="your_password",
        server="sip.example.com",
    ) as client:
        await client.register()
        
        # Create call and configure before connecting
        call = client.create_call("1234567890")
        
        # Configure call identity
        call.set_caller_id("sip:support@company.com")
        call.set_display_name("Support Line")
        
        # Add custom SIP headers
        call.add_header("X-Campaign-ID", "promo123")
        call.add_header("X-Account-ID", "12345")
        
        # Set codec preferences
        call.set_codecs(["pcmu", "pcma"])
        
        # Set up event handlers
        call.on("ringing", lambda: print("Ringing..."))
        call.on("answered", lambda: print("Connected!"))
        
        # Now connect
        await call.connect()
        await call.say("Hello!")
        await call.hangup()

asyncio.run(main())
```

### Handling Incoming Calls

```python
import asyncio
from PySIP import SIPClient

async def main():
    async with SIPClient(
        username="your_username",
        password="your_password", 
        server="sip.example.com",
    ) as client:
        await client.register()
        
        @client.on_incoming_call
        async def handle_call(call):
            await call.answer()
            await call.say("Welcome to PySIP! Press 1 for sales, 2 for support.")
            
            result = await call.gather(max_digits=1, timeout=5)
            
            if result.digits == "1":
                await call.transfer("sales@example.com")
            elif result.digits == "2":
                await call.transfer("support@example.com")
            else:
                await call.say("Invalid option. Goodbye!")
                await call.hangup()
        
        # Keep running
        await asyncio.Event().wait()

asyncio.run(main())
```

### Using Environment Variables

Create a `.env` file:

```bash
SIP_USERNAME=your_username
SIP_PASSWORD=your_password
SIP_SERVER=sip.example.com
```

Then in your code:

```python
import os
from dotenv import load_dotenv
from PySIP import SIPClient

load_dotenv()

client = SIPClient(
    username=os.getenv("SIP_USERNAME"),
    password=os.getenv("SIP_PASSWORD"),
    server=os.getenv("SIP_SERVER"),
)
```

## 📖 Documentation

### Project Structure

```
PySIP/
├── PySIP/
│   ├── __init__.py          # Main exports
│   ├── client.py             # SIPClient - main entry point
│   ├── call.py               # Call handling
│   ├── types.py              # Type definitions
│   ├── exceptions.py         # Custom exceptions
│   ├── protocol/             # Protocol implementations
│   │   ├── sip/              # SIP parser/builder
│   │   ├── sdp/              # SDP parser/builder
│   │   └── rtp/              # RTP packet handling
│   ├── transport/            # Network transports
│   │   ├── udp.py            # UDP transport
│   │   └── rtp.py            # RTP transport
│   ├── media/                # Media handling
│   │   ├── codecs/           # G.711 codecs
│   │   ├── jitter.py         # Jitter buffer
│   │   └── player.py         # Audio player
│   ├── features/             # Optional features
│   │   ├── tts/              # Text-to-speech
│   │   ├── dtmf/             # DTMF detection
│   │   ├── amd/              # Answering machine detection
│   │   └── recording/        # Call recording
│   └── session/              # Session management
│       ├── dialog.py         # SIP dialog state
│       ├── transaction.py    # SIP transactions
│       └── manager.py        # Call manager
├── tests/                    # Test suite
├── pyproject.toml           # Project configuration
└── README.md
```

### Core Classes

#### SIPClient

The main entry point for all SIP operations.

```python
from PySIP import SIPClient

client = SIPClient(
    username="user",
    password="pass",
    server="sip.example.com",
    port=5060,                    # Optional, default 5060
    transport="UDP",              # UDP, TCP, or TLS
    local_port=0,                 # 0 for auto-assign
    user_agent="MyApp/1.0",       # Custom User-Agent
    register_expires=300,         # Registration expiry
    max_concurrent_calls=100,     # Call limit
    rtp_port_range=(10000, 20000) # RTP port range
)
```

#### Call

Represents an active call with media operations.

```python
# Make outbound call (context manager - recommended)
async with client.dial("destination") as call:
    await call.say("Hello!")
    # Auto-hangup on exit

# Advanced: Configure before connecting
call = client.create_call("destination")
call.set_caller_id("sip:support@company.com")   # Override From URI
call.set_display_name("Support Line")            # Caller display name
call.add_header("X-Campaign", "promo")           # Custom SIP headers
call.set_codecs(["pcmu", "pcma"])                # Codec preference
call.set_timeout(30)                             # Connection timeout
call.on("ringing", on_ring_handler)              # Event callbacks
await call.connect()

# Media operations
await call.say("Hello!")                        # TTS
await call.play("audio.wav")                    # Play file
result = await call.gather(max_digits=4)        # Get DTMF (returns GatherResult)
await call.send_dtmf("1234")                    # Send DTMF

# Call control
await call.hold()                               # Put on hold
await call.unhold()                             # Resume
await call.mute()                               # Mute microphone
await call.unmute()                             # Unmute
await call.hangup()
await call.transfer("other@example.com")

# Properties
call.state          # CallState enum
call.call_id        # SIP Call-ID
call.duration       # Call duration in seconds
call.is_active      # True if call is active
```

### Error Handling

```python
from PySIP import SIPClient
from PySIP.exceptions import (
    RegistrationError,
    CallFailedError,
    CallRejectedError,
    CallTimeoutError,
)

try:
    await client.register()
except RegistrationError as e:
    print(f"Registration failed: {e}")

try:
    call = client.dial("destination")
    await call.dial()
except CallTimeoutError:
    print("No answer")
except CallRejectedError as e:
    print(f"Call rejected: {e.status_code} {e.reason}")
except CallFailedError as e:
    print(f"Call failed: {e}")
```

## 🧪 Testing

```bash
# Run all tests
pytest tests/ -v

# Run with coverage
pytest tests/ -v --cov=PySIP
```

## 🔧 Requirements

- Python 3.10+
- numpy
- edge-tts
- uvloop (optional, Linux/macOS only)

## 🤝 Contributing

Contributions are welcome! Please feel free to submit issues and pull requests.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

---

<p align="center">Made with ❤️ by Moha Abdi</p>
