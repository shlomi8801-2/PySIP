#!/usr/bin/env python3
"""
DTMF PIN Collection Example

Makes an outbound call, prompts for a PIN, and validates it.
Demonstrates the GatherResult API.

Usage:
    # With CLI arguments
    python gather_pin.py --to 1234567890 --user alice --pass secret --server sip.example.com
    
    # With environment variables (from .env file)
    python gather_pin.py --to 1234567890
    
    # Show help
    python gather_pin.py --help
"""

import argparse
import asyncio
import os
import sys

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from PySIP import SIPClient, GatherResult
from PySIP.exceptions import (
    CallFailedError,
    CallRejectedError,
    CallTimeoutError,
    RegistrationError,
)

# Load environment variables from .env file
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))

# Valid PINs for demo (in real app, this would be in a database)
VALID_PINS = {"1234", "0000", "9999"}
MAX_ATTEMPTS = 3


def get_args():
    """Parse command line arguments with env var fallbacks."""
    parser = argparse.ArgumentParser(
        description="Make a call and collect PIN via DTMF",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
Environment Variables:
  SIP_USERNAME    SIP account username
  SIP_PASSWORD    SIP account password  
  SIP_SERVER      SIP server hostname
  SIP_PORT        SIP port (default: 5060)
  TEST_NUMBER     Default destination number

Valid test PINs: {', '.join(sorted(VALID_PINS))}

Examples:
  python gather_pin.py --to 1234567890
  python gather_pin.py --to 1234567890 --user alice --pass secret --server sip.example.com
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
    
    return parser.parse_args()


async def collect_and_validate_pin(call) -> bool:
    """
    Collect PIN from user and validate it.
    
    Returns:
        True if PIN was valid, False otherwise
    """
    attempts = 0
    
    while attempts < MAX_ATTEMPTS:
        attempts += 1
        remaining = MAX_ATTEMPTS - attempts
        
        # Prompt for PIN
        await call.say(f"Please enter your 4 digit PIN, followed by the pound key.")
        
        # Collect digits
        # - max_digits=4: Collect up to 4 digits
        # - timeout=10: Wait up to 10 seconds
        # - finish_on_key="#": User can press # to submit early
        result: GatherResult = await call.gather(
            max_digits=4,
            timeout=10,
            finish_on_key="#",
        )
        
        print(f"Gather result: digits='{result.digits}', terminated_by='{result.terminated_by}'")
        
        # Check termination reason
        if result.terminated_by == "hangup":
            print("Caller hung up during PIN entry")
            return False
        
        if result.terminated_by == "timeout" and not result.digits:
            await call.say("I didn't receive any input.")
            if remaining > 0:
                await call.say(f"You have {remaining} attempts remaining.")
            continue
        
        # Validate PIN
        pin = result.digits
        
        if len(pin) < 4:
            await call.say(f"PIN must be 4 digits. You entered {len(pin)} digits.")
            if remaining > 0:
                await call.say(f"You have {remaining} attempts remaining.")
            continue
        
        if pin in VALID_PINS:
            await call.say("PIN accepted. Access granted!")
            return True
        else:
            await call.say("Invalid PIN.")
            if remaining > 0:
                await call.say(f"You have {remaining} attempts remaining.")
    
    await call.say("Maximum attempts exceeded. Access denied. Goodbye.")
    return False


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
    
    print(f"PIN Collection Demo")
    print(f"==================")
    print(f"Server: {args.server}:{args.port}")
    print(f"Destination: {args.to}")
    print(f"Valid PINs for testing: {', '.join(sorted(VALID_PINS))}")
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
                await call.say("Welcome to the PIN verification system.")
                
                # Collect and validate PIN
                success = await collect_and_validate_pin(call)
                
                if success:
                    print("PIN validation: SUCCESS")
                    # In a real app, you might transfer or continue with authenticated flow
                    await call.say("Thank you. This demo will now end. Goodbye!")
                else:
                    print("PIN validation: FAILED")
                
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
