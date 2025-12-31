#!/usr/bin/env python3
"""
Answering Machine Detection (AMD) Example

Makes an outbound call, detects if answered by human or machine,
and responds appropriately.

Usage:
    # With CLI arguments
    python amd_detection.py --to 1234567890 --user alice --pass secret --server sip.example.com
    
    # With environment variables (from .env file)
    python amd_detection.py --to 1234567890
    
    # Show help
    python amd_detection.py --help
"""

import argparse
import asyncio
import os
import sys

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from PySIP import SIPClient, AMDResultType
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
        description="Make a call with answering machine detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Environment Variables:
  SIP_USERNAME    SIP account username
  SIP_PASSWORD    SIP account password  
  SIP_SERVER      SIP server hostname
  SIP_PORT        SIP port (default: 5060)
  TEST_NUMBER     Default destination number

Examples:
  python amd_detection.py --to 1234567890
  python amd_detection.py --to 1234567890 --amd-timeout 7
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
        '--amd-timeout',
        type=float,
        default=5.0,
        help='AMD detection timeout in seconds (default: 5)'
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
    
    print(f"AMD Detection Demo")
    print(f"==================")
    print(f"Server: {args.server}:{args.port}")
    print(f"Destination: {args.to}")
    print(f"AMD timeout: {args.amd_timeout}s")
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
            # Create call (don't use context manager since we need AMD before answering)
            call = client.dial(args.to)
            await call.dial()
            
            print(f"Call connected! Call-ID: {call.call_id}")
            print("Running answering machine detection...")
            
            # Run AMD
            # This analyzes the first few seconds of audio to detect:
            # - HUMAN: Short greeting, natural pauses
            # - MACHINE: Long greeting, typical voicemail patterns
            # - UNKNOWN: Couldn't determine
            amd_result = await call.detect_answering_machine(timeout=args.amd_timeout)
            
            print(f"\nAMD Result:")
            print(f"  Type: {amd_result.result_type.value}")
            print(f"  Confidence: {amd_result.confidence:.0%}")
            print(f"  Duration: {amd_result.detection_time:.2f}s")
            
            # Handle based on result
            if amd_result.result_type == AMDResultType.HUMAN:
                print("\n>>> Detected: HUMAN - Delivering live message")
                await call.say(
                    "Hello! This is a live call from Py SIP. "
                    "Thank you for answering. "
                    "This is just a test call. Have a great day!"
                )
                
            elif amd_result.result_type == AMDResultType.MACHINE:
                print("\n>>> Detected: MACHINE - Leaving voicemail")
                # Wait for beep (simplified - real implementation would detect it)
                await asyncio.sleep(2)
                await call.say(
                    "Hello, this is an automated message from Py SIP. "
                    "Please call us back at your convenience. "
                    "Thank you and goodbye."
                )
                
            else:  # UNKNOWN or NOTSURE
                print("\n>>> Detected: UNKNOWN - Using fallback message")
                await call.say(
                    "Hello! This is a call from Py SIP. "
                    "If you are a person, please press 1. "
                    "Otherwise, please disregard this message."
                )
                
                # Try to get confirmation
                result = await call.gather(max_digits=1, timeout=5)
                if result.digits == "1":
                    print("Human confirmed via DTMF")
                    await call.say("Thank you for confirming. This was just a test. Goodbye!")
            
            await call.hangup()
            
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
