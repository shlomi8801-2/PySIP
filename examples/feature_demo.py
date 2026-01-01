#!/usr/bin/env python3
"""
Demo script for PySIP v2 advanced features.

Demonstrates:
- RTCP quality metrics with RTT calculation (RFC 3550)
- RTCP-MUX support (RFC 5761)
- Session timers (RFC 4028)
- Call transfer via REFER (RFC 3515)

Usage:
    python examples/feature_demo.py --to 100
    python examples/feature_demo.py --to 100 --test rtcp
    python examples/feature_demo.py --to 100 --test rtcp-mux
    
Environment variables:
    SIP_USERNAME - SIP account username
    SIP_PASSWORD - SIP account password  
    SIP_SERVER   - SIP server address
    SIP_PORT     - SIP server port (default: 5060)
"""

import argparse
import asyncio
import os
import sys

# Add parent directory to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from PySIP import SIPClient


async def test_rtcp_metrics(client: SIPClient, to_number: str):
    """Test RTCP quality metrics during a call including RTT calculation."""
    print("\n" + "=" * 50)
    print("TEST: RTCP Quality Metrics (RFC 3550)")
    print("=" * 50)
    
    async with client.dial(to_number) as call:
        print(f"✓ Call connected: {call.call_id}")
        
        # Play some audio
        await call.say("Testing RTCP quality metrics. Please wait for statistics.")
        
        # Wait for multiple RTCP reports to be exchanged
        # RTCP uses randomized interval (2.5-7.5 seconds with base 5s)
        print("⏳ Waiting for RTCP reports (10 seconds)...")
        await asyncio.sleep(10)
        
        # Check RTP session stats
        if call._rtp_session:
            stats = call._rtp_session.stats
            session = call._rtp_session
            
            print(f"\n📊 RTP/RTCP Statistics:")
            print(f"   ─────────────────────────────────")
            print(f"   Packets sent:     {stats.packets_sent}")
            print(f"   Packets received: {stats.packets_received}")
            print(f"   Packets lost:     {stats.packets_lost}")
            print(f"   ─────────────────────────────────")
            print(f"   Jitter:           {stats.jitter:.2f} ms")
            print(f"   RTT:              {stats.rtt:.2f} ms")
            print(f"   ─────────────────────────────────")
            print(f"   Bytes sent:       {stats.bytes_sent}")
            print(f"   Bytes received:   {stats.bytes_received}")
            print(f"   ─────────────────────────────────")
            print(f"   Local SSRC:       {session._ssrc:#010x}")
            if session._remote_ssrc:
                print(f"   Remote SSRC:      {session._remote_ssrc:#010x}")
            if session._ssrc_collision_count > 0:
                print(f"   SSRC collisions:  {session._ssrc_collision_count}")
        
        await call.say("Statistics collected. Goodbye.")
    
    print("✓ RTCP test complete")


async def test_rtcp_mux(client: SIPClient, to_number: str):
    """Test RTCP-MUX - RTP and RTCP on the same port (RFC 5761)."""
    print("\n" + "=" * 50)
    print("TEST: RTCP-MUX (RFC 5761)")
    print("=" * 50)
    
    # Create call with RTCP-MUX enabled
    call = client.create_call(to_number)
    
    # Configure RTCP-MUX through RTP config
    # Note: This would need to be set before call connects
    print("ℹ️  RTCP-MUX multiplexes RTP and RTCP on the same port")
    print("   This improves NAT traversal and is required by WebRTC")
    
    await call.connect()
    print(f"✓ Call connected: {call.call_id}")
    
    await call.say("Testing RTCP MUX. RTP and RTCP are on the same port.")
    
    # Wait for RTCP exchange
    await asyncio.sleep(8)
    
    if call._rtp_session:
        session = call._rtp_session
        rtp_addr = session.local_address
        
        print(f"\n📡 Transport Info:")
        print(f"   RTP address:  {rtp_addr[0]}:{rtp_addr[1]}")
        if session._config.rtcp_mux:
            print(f"   RTCP:         Same port (MUX enabled)")
        else:
            print(f"   RTCP address: {rtp_addr[0]}:{rtp_addr[1] + 1}")
        
        stats = session.stats
        print(f"\n📊 Statistics:")
        print(f"   Packets sent/recv: {stats.packets_sent}/{stats.packets_received}")
        print(f"   Jitter: {stats.jitter:.2f} ms, RTT: {stats.rtt:.2f} ms")
    
    await call.say("RTCP MUX test complete.")
    await call.hangup()
    
    print("✓ RTCP-MUX test complete")


async def test_session_timer(client: SIPClient, to_number: str):
    """Test session timer with short refresh interval."""
    print("\n" + "=" * 50)
    print("TEST: Session Timer (RFC 4028)")
    print("=" * 50)
    
    call = client.create_call(to_number)
    
    # Set short session timer for testing (90 seconds minimum per RFC)
    call.set_session_timer(expires=90, min_se=90)
    
    print(f"✓ Session timer configured: {call._session_expires}s expires")
    
    await call.connect()
    print(f"✓ Call connected: {call.call_id}")
    
    await call.say("Testing session timers. The call will refresh automatically.")
    
    # Wait to observe timer behavior
    print("⏳ Waiting 50 seconds to observe session timer...")
    await asyncio.sleep(50)
    
    # Check if session timer task is running
    if call._session_timer_task:
        print("✓ Session timer task is active")
    
    await call.say("Session timer test complete.")
    await call.hangup()
    
    print("✓ Session timer test complete")


async def test_transfer(client: SIPClient, from_number: str, transfer_to: str):
    """Test call transfer (REFER)."""
    print("\n" + "=" * 50)
    print("TEST: Call Transfer (RFC 3515 REFER)")
    print("=" * 50)
    
    async with client.dial(from_number) as call:
        print(f"✓ Call connected: {call.call_id}")
        
        await call.say(f"This call will now be transferred to {transfer_to}.")
        
        # Wait a moment
        await asyncio.sleep(1)
        
        # Initiate transfer
        print(f"📞 Initiating transfer to {transfer_to}...")
        await call.transfer(f"sip:{transfer_to}@{client._config.server}")
        
        print("✓ REFER sent")
        
        # Give time for transfer to process
        await asyncio.sleep(5)
    
    print("✓ Transfer test complete")


async def test_incoming_refer(client: SIPClient):
    """Test handling incoming REFER requests."""
    print("\n" + "=" * 50)
    print("TEST: Incoming REFER Handling")
    print("=" * 50)
    
    transfer_target = None
    
    async def handle_call(call):
        nonlocal transfer_target
        
        # Register transfer handler
        def on_transfer(target_uri):
            nonlocal transfer_target
            print(f"📞 Received transfer request to: {target_uri}")
            transfer_target = target_uri
        
        call.on("transfer", on_transfer)
        
        await call.answer()
        print(f"✓ Call answered: {call.call_id}")
        
        await call.say("Waiting for transfer request...")
        
        # Wait for possible transfer
        await asyncio.sleep(30)
        
        if transfer_target:
            print(f"✓ Would transfer to: {transfer_target}")
        
        await call.hangup()
    
    client.on_incoming_call(handle_call)
    
    print(f"📞 Waiting for incoming call...")
    print(f"   Call {client._config.username}@{client._config.server} to test")
    print(f"   Then initiate a transfer from the calling device")
    
    # Wait for test
    await asyncio.sleep(60)


async def main():
    parser = argparse.ArgumentParser(description="Test new PySIP v2 features")
    parser.add_argument("--username", default=os.getenv("SIP_USERNAME"), help="SIP username")
    parser.add_argument("--password", default=os.getenv("SIP_PASSWORD"), help="SIP password")
    parser.add_argument("--server", default=os.getenv("SIP_SERVER"), help="SIP server")
    parser.add_argument("--port", type=int, default=int(os.getenv("SIP_PORT", "5060")), help="SIP port")
    parser.add_argument("--to", required=True, help="Number to call for testing")
    parser.add_argument("--transfer-to", help="Number to transfer to (for transfer test)")
    parser.add_argument(
        "--test",
        choices=["rtcp", "rtcp-mux", "session-timer", "transfer", "incoming-refer", "all"],
        default="all",
        help="Which test to run",
    )
    
    args = parser.parse_args()
    
    if not all([args.username, args.password, args.server]):
        print("Error: Missing credentials. Set SIP_USERNAME, SIP_PASSWORD, SIP_SERVER")
        print("       or use --username, --password, --server arguments")
        sys.exit(1)
    
    print("PySIP v2 New Features Test")
    print("=" * 50)
    print(f"Server:   {args.server}:{args.port}")
    print(f"Username: {args.username}")
    print(f"To:       {args.to}")
    
    async with SIPClient(
        server=args.server,
        port=args.port,
        username=args.username,
        password=args.password,
    ) as client:
        await client.register()
        print("✓ Registered with SIP server")
        
        tests_to_run = []
        
        if args.test in ("all", "rtcp"):
            tests_to_run.append(("RTCP Metrics", test_rtcp_metrics(client, args.to)))
        
        if args.test in ("all", "rtcp-mux"):
            tests_to_run.append(("RTCP-MUX", test_rtcp_mux(client, args.to)))
        
        if args.test in ("all", "session-timer"):
            tests_to_run.append(("Session Timer", test_session_timer(client, args.to)))
        
        if args.test in ("transfer",) and args.transfer_to:
            tests_to_run.append(("Transfer", test_transfer(client, args.to, args.transfer_to)))
        
        if args.test == "incoming-refer":
            tests_to_run.append(("Incoming REFER", test_incoming_refer(client)))
        
        for name, coro in tests_to_run:
            try:
                await coro
            except Exception as e:
                print(f"✗ {name} failed: {e}")
    
    print("\n" + "=" * 50)
    print("All tests complete!")


if __name__ == "__main__":
    asyncio.run(main())

