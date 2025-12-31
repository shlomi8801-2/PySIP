# PySIP Examples

Ready-to-run example scripts for testing PySIP functionality.

## Quick Start

### 1. Install Dependencies

```bash
pip install PySIPio python-dotenv
```

Or for development (from repository root):

```bash
pip install -e .
pip install python-dotenv
```

### 2. Configure Credentials

You have two options:

**Option A: Environment variables (recommended)**

Copy the example config and edit:

```bash
cp .env.example .env
# Edit .env with your SIP credentials
```

**Option B: Command line arguments**

Pass credentials directly:

```bash
python examples/basic_call.py --to 123456 --user alice --pass secret --server sip.example.com
```

### 3. Run an Example

```bash
# Using .env file
python examples/basic_call.py --to 1234567890

# Or with all arguments
python examples/basic_call.py --to 1234567890 --user alice --pass secret --server sip.example.com

# Show help for any script
python examples/basic_call.py --help
```

## Available Examples

| Script | Description |
|--------|-------------|
| `basic_call.py` | Simple outbound call with TTS greeting |
| `ivr_menu.py` | Incoming call handler with IVR menu |
| `gather_pin.py` | DTMF collection and PIN validation |
| `record_call.py` | Call recording to WAV file |
| `amd_detection.py` | Answering machine detection |

## Example Details

### basic_call.py - Simple Outbound Call

Makes an outbound call, plays a TTS greeting, and hangs up.

```bash
# Basic usage
python examples/basic_call.py --to 1234567890

# Custom message
python examples/basic_call.py --to 1234567890 --message "Hello from PySIP!"

# Show all options
python examples/basic_call.py --help
```

### ivr_menu.py - IVR Menu Server

Registers with the SIP server and handles incoming calls with an interactive menu:
- Press 1: Hear a greeting
- Press 2: Hear the current time
- Press 3: End the call
- Press *: Repeat menu

```bash
python examples/ivr_menu.py
# Then call your SIP extension to test
```

### gather_pin.py - PIN Collection

Demonstrates DTMF digit collection with the `GatherResult` API:
- Calls the destination
- Prompts for 4-digit PIN
- Validates against known PINs (1234, 0000, 9999)
- Shows termination reason handling

```bash
python examples/gather_pin.py --to 1234567890
```

### record_call.py - Call Recording

Records incoming audio and saves to a WAV file:
- Calls the destination
- Records up to 30 seconds (or 10s of silence)
- Saves to `recording_<call_id>.wav`

```bash
# Default settings (30s max, 10s silence timeout)
python examples/record_call.py --to 1234567890

# Custom recording settings
python examples/record_call.py --to 1234567890 --max-duration 60 --silence-timeout 5
```

### amd_detection.py - Answering Machine Detection

Detects if the call is answered by a human or machine:
- Analyzes the first few seconds of audio
- Delivers different messages based on detection
- Shows confidence score and detection time

```bash
python examples/amd_detection.py --to 1234567890

# Longer detection timeout
python examples/amd_detection.py --to 1234567890 --amd-timeout 7
```

## Command Line Arguments

All examples support these common arguments:

| Argument | Env Variable | Description |
|----------|--------------|-------------|
| `--to`, `-t` | `TEST_NUMBER` | Destination number to call |
| `--user`, `-u` | `SIP_USERNAME` | SIP username |
| `--pass`, `-p` | `SIP_PASSWORD` | SIP password |
| `--server`, `-s` | `SIP_SERVER` | SIP server hostname |
| `--port` | `SIP_PORT` | SIP port (default: 5060) |

CLI arguments take precedence over environment variables.

## Environment Variables

Create a `.env` file in the project root (copy from `.env.example`):

```bash
# Required
SIP_USERNAME=your_extension
SIP_PASSWORD=your_password
SIP_SERVER=sip.example.com

# Optional
SIP_PORT=5060
TEST_NUMBER=1234567890
LOCAL_IP=192.168.1.100
TTS_VOICE=en-US-GuyNeural
```

## Common Issues

### "Missing required arguments"

Either:
- Copy `.env.example` to `.env` and fill in credentials, OR
- Pass `--user`, `--pass`, and `--server` as arguments

### "Registration failed"

- Check your SIP credentials
- Ensure the SIP server is reachable
- Check if your IP is allowed by the server

### "Call rejected: 403 Forbidden"

- Your account may not have permission to call the destination
- Check if the destination number format is correct

### "Call failed: No answer (timeout)"

- The destination didn't answer within the timeout
- Try a different number or increase the timeout

### "ModuleNotFoundError: No module named 'PySIP'"

- Install PySIP: `pip install PySIPio`
- Or for development: `pip install -e .` from repository root
