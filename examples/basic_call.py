#!/usr/bin/env python3
"""
Basic Outbound Call Example

Makes an outbound call, plays a TTS greeting, and hangs up.

Usage:
    # With CLI arguments
    python basic_call.py --to 1234567890 --user alice --pass secret --server sip.example.com
    
    # With environment variables (from .env file)
    python basic_call.py --to 1234567890
    
    # Show help
    python basic_call.py --help
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

# Load environment variables from .env file (check both current and parent dir)
load_dotenv()  # Current directory
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))  # Parent directory


def get_args():
    """Parse command line arguments with env var fallbacks."""
    parser = argparse.ArgumentParser(
        description="Make an outbound SIP call with TTS greeting",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SIP_USERNAME    SIP account username
  SIP_PASSWORD    SIP account password  
  SIP_SERVER      SIP server hostname
  SIP_PORT        SIP port (default: 5060)
  TEST_NUMBER     Default destination number

Examples:
  python basic_call.py --to 1234567890
  python basic_call.py --to 1234567890 --user alice --pass secret --server sip.example.com
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
        '--message', '-m',
        default="Hello! This is a test call from Py SIP. Thank you for testing. Goodbye!",
        help='TTS message to play'
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
    
    print(f"Basic Call Demo")
    print(f"===============")
    print(f"Server: {args.server}:{args.port}")
    print(f"Username: {args.user}")
    print(f"Destination: {args.to}")
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
            # Use context manager for automatic cleanup
            async with client.dial(args.to) as call:
                print(f"Call connected! Call-ID: {call.call_id}")
                
                # Play TTS greeting (say() waits for playback to complete)
                print("Playing greeting...")
                await call.say(args.message)
                
                print(f"Call duration: {call.duration:.1f} seconds")
                # Auto-hangup when exiting context
            
            print("Call ended successfully!")
            
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
