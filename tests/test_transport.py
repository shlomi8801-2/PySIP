"""
Tests for transport layer.
"""

import asyncio
import pytest
from PySIP.transport import UDPTransport
from PySIP.transport.rtp import RTPSession, RTPConfig
from PySIP.types import TransportState


@pytest.fixture
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


class TestUDPTransport:
    """Tests for UDP transport."""
    
    @pytest.mark.asyncio
    async def test_bind(self):
        transport = UDPTransport()
        
        await transport.bind(("127.0.0.1", 0))
        
        assert transport.state == TransportState.CONNECTED
        assert transport.local_address is not None
        assert transport.local_address[0] == "127.0.0.1"
        
        await transport.close()
    
    @pytest.mark.asyncio
    async def test_send_receive(self):
        # Create two transports
        transport1 = UDPTransport()
        transport2 = UDPTransport()
        
        await transport1.bind(("127.0.0.1", 0))
        await transport2.bind(("127.0.0.1", 0))
        
        received = []
        transport2.on_data_received(lambda data, addr: received.append(data))
        
        # Send from transport1 to transport2
        addr2 = transport2.local_address
        await transport1.send(b"Hello", addr2)
        
        # Wait for receive
        await asyncio.sleep(0.1)
        
        assert len(received) == 1
        assert received[0] == b"Hello"
        
        await transport1.close()
        await transport2.close()
    
    @pytest.mark.asyncio
    async def test_close(self):
        transport = UDPTransport()
        
        await transport.bind(("127.0.0.1", 0))
        await transport.close()
        
        assert transport.state == TransportState.CLOSED


class TestRTPSession:
    """Tests for RTP session."""
    
    @pytest.mark.asyncio
    async def test_start_stop(self):
        config = RTPConfig(local_ip="127.0.0.1", local_port=0)
        session = RTPSession(config)
        
        await session.start()
        
        assert session.is_running
        assert session.local_address is not None
        
        await session.stop()
        
        assert not session.is_running
    
    @pytest.mark.asyncio
    async def test_send_packet(self):
        config1 = RTPConfig(local_ip="127.0.0.1", local_port=0)
        config2 = RTPConfig(local_ip="127.0.0.1", local_port=0)
        
        session1 = RTPSession(config1)
        session2 = RTPSession(config2)
        
        await session1.start()
        await session2.start()
        
        received = []
        session2.on_packet(lambda data, addr: received.append(data))
        
        # Configure session1 to send to session2
        session1.set_remote_address(session2.local_address)
        
        # Send packet
        session1.send(b"\x00" * 160)
        
        # Wait
        await asyncio.sleep(0.1)
        
        assert len(received) == 1
        # Packet should have 12-byte RTP header + 160 payload
        assert len(received[0]) == 172
        
        await session1.stop()
        await session2.stop()
    
    @pytest.mark.asyncio
    async def test_ssrc_generation(self):
        session = RTPSession()
        
        assert session.ssrc > 0
        assert session.ssrc <= 0xFFFFFFFF
    
    @pytest.mark.asyncio
    async def test_stats(self):
        config = RTPConfig(local_ip="127.0.0.1", local_port=0)
        session = RTPSession(config)
        
        await session.start()
        session.set_remote_address(("127.0.0.1", 12345))
        
        session.send(b"\x00" * 160)
        session.send(b"\x00" * 160)
        
        stats = session.stats
        assert stats.packets_sent == 2
        assert stats.bytes_sent == 2 * 172  # header + payload
        
        await session.stop()


