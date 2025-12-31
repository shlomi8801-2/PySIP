#!/usr/bin/env python3
"""
Advanced Outbound Call Example

Demonstrates power-user features:
- Custom caller ID and display name
- Custom SIP headers
- Codec preferences
- Event callbacks (ringing, answered, hangup)
- Connection timeout

Usage:
    python advanced_call.py --to 1234567890 --user alice --pass secret --server sip.example.com
    python advanced_call.py --to 1234567890 --caller-id "sip:support@company.com" --display-name "Support"
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

# Load environment variables
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


def get_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Advanced outbound call with custom configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic call with custom caller ID
  python advanced_call.py --to 123 --caller-id "sip:sales@company.com"
  
  # With display name and custom headers
  python advanced_call.py --to 123 --display-name "Sales Team" --header "X-Campaign:promo2024"
  
  # Multiple custom headers
  python advanced_call.py --to 123 --header "X-Account:12345" --header "X-Priority:high"
        """
    )
    
    # Required
    parser.add_argument('--to', '-t', default=os.getenv('TEST_NUMBER'),
                        help='Destination number')
    parser.add_argument('--user', '-u', default=os.getenv('SIP_USERNAME'),
                        help='SIP username')
    parser.add_argument('--pass', '-p', dest='password', default=os.getenv('SIP_PASSWORD'),
                        help='SIP password')
    parser.add_argument('--server', '-s', default=os.getenv('SIP_SERVER'),
                        help='SIP server')
    parser.add_argument('--port', type=int, default=int(os.getenv('SIP_PORT', '5060')),
                        help='SIP port')
    
    # Advanced options
    parser.add_argument('--caller-id', default=None,
                        help='Custom caller ID (SIP URI)')
    parser.add_argument('--display-name', default=None,
                        help='Display name shown on recipient phone')
    parser.add_argument('--header', action='append', default=[],
                        help='Custom SIP header (format: "Name:Value"). Can be used multiple times.')
    parser.add_argument('--codecs', default='pcmu,pcma',
                        help='Comma-separated codec preference (default: pcmu,pcma)')
    parser.add_argument('--timeout', type=int, default=30,
                        help='Connection timeout in seconds (default: 30)')
    parser.add_argument('--user-agent', default=None,
                        help='Custom User-Agent header')
    parser.add_argument('--message', '-m',
                        default="Hello! This call was made using advanced PySIP features. Goodbye!",
                        help='TTS message to play')
    
    return parser.parse_args()


def on_ringing():
    """Called when the remote party is ringing."""
    print("  📞 Remote party is ringing...")


def on_answered():
    """Called when the call is answered."""
    print("  ✅ Call answered!")


def on_hangup():
    """Called when the call ends."""
    print("  📴 Call ended")


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
        sys.exit(1)
    
    # Parse custom headers
    custom_headers = {}
    for header in args.header:
        if ':' in header:
            name, value = header.split(':', 1)
            custom_headers[name.strip()] = value.strip()
        else:
            print(f"Warning: Invalid header format '{header}', expected 'Name:Value'")
    
    # Parse codecs
    codecs = [c.strip() for c in args.codecs.split(',')]
    
    print("Advanced Call Demo")
    print("==================")
    print(f"Server: {args.server}:{args.port}")
    print(f"Destination: {args.to}")
    print()
    print("Configuration:")
    if args.caller_id:
        print(f"  Caller ID: {args.caller_id}")
    if args.display_name:
        print(f"  Display Name: {args.display_name}")
    if custom_headers:
        print(f"  Custom Headers: {custom_headers}")
    print(f"  Codecs: {codecs}")
    print(f"  Timeout: {args.timeout}s")
    if args.user_agent:
        print(f"  User-Agent: {args.user_agent}")
    print()
    
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
        
        print(f"\nCreating call to {args.to}...")
        
        try:
            # Create unconfigured call
            call = client.create_call(args.to)
            
            # Configure caller identity
            if args.caller_id:
                call.set_caller_id(args.caller_id)
            if args.display_name:
                call.set_display_name(args.display_name)
            
            # Add custom SIP headers
            for name, value in custom_headers.items():
                call.add_header(name, value)
            
            # Set codec preferences
            call.set_codecs(codecs)
            
            # Set timeout
            call.set_timeout(args.timeout)
            
            # Override user agent if specified
            if args.user_agent:
                call.set_user_agent(args.user_agent)
            
            # Register event callbacks
            call.on("ringing", on_ringing)
            call.on("answered", on_answered)
            call.on("hangup", on_hangup)
            
            # Now connect
            print("\nConnecting...")
            await call.connect()
            
            print(f"Call-ID: {call.call_id}")
            
            # Play message
            print("\nPlaying message...")
            await call.say(args.message)
            
            # Hang up
            print("\nHanging up...")
            await call.hangup()
            
            print(f"\nCall duration: {call.duration:.1f} seconds")
            
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

