#!/usr/bin/env python3
"""
Call Recording Example

Makes an outbound call, records the audio, and saves it to a WAV file.

Usage:
    # With CLI arguments
    python record_call.py --to 1234567890 --user alice --pass secret --server sip.example.com
    
    # With environment variables (from .env file)
    python record_call.py --to 1234567890
    
    # Show help
    python record_call.py --help
        
Output:
    Saves recording to: recording_<call_id>.wav
"""

import argparse
import asyncio
import os
import sys

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from PySIP import SIPClient
from PySIP.exceptions import (
    CallFailedError,
    CallRejectedError,
    CallTimeoutError,
    RegistrationError,
)

# Load environment variables from .env file
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


def get_args():
    """Parse command line arguments with env var fallbacks."""
    parser = argparse.ArgumentParser(
        description="Make a call and record audio to WAV file",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SIP_USERNAME    SIP account username
  SIP_PASSWORD    SIP account password  
  SIP_SERVER      SIP server hostname
  SIP_PORT        SIP port (default: 5060)
  TEST_NUMBER     Default destination number

Examples:
  python record_call.py --to 1234567890
  python record_call.py --to 1234567890 --max-duration 60
        """
    )
    
    parser.add_argument(
        '--to', '-t',
        default=os.getenv('TEST_NUMBER'),
        help='Destination number to call (or TEST_NUMBER env var)'
    )
    parser.add_argument(
        '--user', '-u',
        default=os.getenv('SIP_USERNAME'),
        help='SIP username (or SIP_USERNAME env var)'
    )
    parser.add_argument(
        '--pass', '-p',
        dest='password',
        default=os.getenv('SIP_PASSWORD'),
        help='SIP password (or SIP_PASSWORD env var)'
    )
    parser.add_argument(
        '--server', '-s',
        default=os.getenv('SIP_SERVER'),
        help='SIP server hostname (or SIP_SERVER env var)'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv('SIP_PORT', '5060')),
        help='SIP port (default: 5060)'
    )
    parser.add_argument(
        '--max-duration',
        type=float,
        default=30.0,
        help='Maximum recording duration in seconds (default: 30)'
    )
    parser.add_argument(
        '--silence-timeout',
        type=float,
        default=10.0,
        help='Stop recording after this many seconds of silence (default: 10)'
    )
    
    return parser.parse_args()


async def main():
    args = get_args()
    
    # Validate required arguments
    missing = []
    if not args.user:
        missing.append('--user or SIP_USERNAME')
    if not args.password:
        missing.append('--pass or SIP_PASSWORD')
    if not args.server:
        missing.append('--server or SIP_SERVER')
    if not args.to:
        missing.append('--to or TEST_NUMBER')
    
    if missing:
        print("Error: Missing required arguments:")
        for m in missing:
            print(f"  - {m}")
        print("\nRun with --help for usage information.")
        print("Or copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    
    print(f"Call Recording Demo")
    print(f"==================")
    print(f"Server: {args.server}:{args.port}")
    print(f"Destination: {args.to}")
    print(f"Max duration: {args.max_duration}s")
    print(f"Silence timeout: {args.silence_timeout}s")
    print()
    
    # Create SIP client
    async with SIPClient(
        username=args.user,
        password=args.password,
        server=args.server,
        port=args.port,
    ) as client:
        print("Registering with SIP server...")
        
        try:
            await client.register()
            print("Registration successful!")
        except RegistrationError as e:
            print(f"Registration failed: {e}")
            sys.exit(1)
        
        print(f"\nDialing {args.to}...")
        
        try:
            async with client.dial(args.to) as call:
                print(f"Call connected! Call-ID: {call.call_id}")
                
                # Welcome message
                await call.say(
                    "Hello! This call is being recorded. "
                    "Please say something after the beep. "
                    f"Recording will stop after {int(args.silence_timeout)} seconds of silence "
                    f"or {int(args.max_duration)} seconds total."
                )
                
                # Play a beep sound (using TTS as placeholder)
                await call.say("Beep!")
                
                # Start recording
                print("\nRecording started...")
                print(f"(Recording for up to {args.max_duration}s, or {args.silence_timeout}s of silence)")
                
                recording = await call.record(
                    max_duration=args.max_duration,
                    silence_timeout=args.silence_timeout,
                )
                
                print(f"\nRecording finished!")
                print(f"  Duration: {recording.duration:.1f} seconds")
                print(f"  Samples: {len(recording.audio_data)} bytes")
                
                # Save to file
                filename = f"recording_{call.call_id[:8]}.wav"
                recording.save(filename)
                print(f"  Saved to: {filename}")
                
                # Thank you message
                await call.say(
                    "Thank you for your recording. "
                    "The audio has been saved. Goodbye!"
                )
                
                # Auto-hangup on context exit
            
            print(f"\nCall ended. Duration: {call.duration:.1f} seconds")
            
        except CallTimeoutError:
            print("Call failed: No answer (timeout)")
        except CallRejectedError as e:
            print(f"Call rejected: {e.status_code} {e.reason}")
        except CallFailedError as e:
            print(f"Call failed: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nInterrupted by user")
