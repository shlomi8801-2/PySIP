#!/usr/bin/env python3
"""
IVR Menu Example

Registers with SIP server and handles incoming calls with an interactive menu.

Usage:
    # With CLI arguments
    python ivr_menu.py --user alice --pass secret --server sip.example.com
    
    # With environment variables (from .env file)
    python ivr_menu.py
    
    # Show help
    python ivr_menu.py --help

Then call your SIP extension to test the IVR.
Press Ctrl+C to stop the server.
"""

import argparse
import asyncio
import os
import sys

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from PySIP import SIPClient, Call
from PySIP.exceptions import RegistrationError

# Load environment variables from .env file
load_dotenv()
load_dotenv(os.path.join(os.path.dirname(__file__), '..', '.env'))


def get_args():
    """Parse command line arguments with env var fallbacks."""
    parser = argparse.ArgumentParser(
        description="Run an IVR menu server for incoming calls",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SIP_USERNAME    SIP account username
  SIP_PASSWORD    SIP account password  
  SIP_SERVER      SIP server hostname
  SIP_PORT        SIP port (default: 5060)

Examples:
  python ivr_menu.py
  python ivr_menu.py --user alice --pass secret --server sip.example.com
        """
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


async def handle_incoming_call(call: Call):
    """Handle an incoming call with IVR menu."""
    print(f"\n{'='*50}")
    print(f"Incoming call! Call-ID: {call.call_id}")
    print(f"{'='*50}")
    
    try:
        # Answer the call
        await call.answer()
        print("Call answered")
        
        # Welcome message
        await call.say(
            "Welcome to Py SIP demo. "
            "Press 1 for a greeting. "
            "Press 2 to hear the time. "
            "Press 3 to end the call. "
            "Press star to hear this menu again."
        )
        
        # Main IVR loop
        while call.is_active:
            # Wait for user input
            result = await call.gather(max_digits=1, timeout=10, finish_on_key=None)
            
            print(f"User pressed: '{result.digits}' (terminated by: {result.terminated_by})")
            
            if result.terminated_by == "hangup":
                print("Caller hung up")
                break
            
            if result.terminated_by == "timeout" and not result.digits:
                await call.say("I didn't hear anything. Please try again.")
                continue
            
            digit = result.digits
            
            if digit == "1":
                await call.say("Hello! Thank you for testing Py SIP. This is option 1.")
            
            elif digit == "2":
                import datetime
                now = datetime.datetime.now()
                time_str = now.strftime("%I:%M %p")
                await call.say(f"The current time is {time_str}.")
            
            elif digit == "3":
                await call.say("Thank you for calling. Goodbye!")
                break
            
            elif digit == "*":
                await call.say(
                    "Press 1 for a greeting. "
                    "Press 2 to hear the time. "
                    "Press 3 to end the call."
                )
            
            else:
                await call.say(f"You pressed {digit}. That is not a valid option.")
        
        # Hang up
        if call.is_active:
            await call.hangup()
        
        print(f"Call ended. Duration: {call.duration:.1f} seconds")
        
    except Exception as e:
        print(f"Error handling call: {e}")
        if call.is_active:
            await call.hangup()


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
    
    if missing:
        print("Error: Missing required arguments:")
        for m in missing:
            print(f"  - {m}")
        print("\nRun with --help for usage information.")
        print("Or copy .env.example to .env and fill in your credentials.")
        sys.exit(1)
    
    print(f"IVR Menu Server")
    print(f"===============")
    print(f"Server: {args.server}:{args.port}")
    print(f"Username: {args.user}")
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
        
        # Set up incoming call handler
        @client.on_incoming_call
        async def on_call(call: Call):
            await handle_incoming_call(call)
        
        print(f"\nWaiting for incoming calls...")
        print(f"Call {args.user}@{args.server} to test the IVR")
        print("Press Ctrl+C to stop\n")
        
        # Keep running until interrupted
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\nServer stopped by user")
