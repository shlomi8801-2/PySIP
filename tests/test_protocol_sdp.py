"""
Tests for SDP protocol implementation.
"""

import pytest
from PySIP.protocol.sdp import SDPParser, SDPBuilder, SDPMessage


class TestSDPParser:
    """Tests for SDP parsing."""
    
    def test_parse_simple_sdp(self):
        sdp_data = b"""v=0
o=- 0 0 IN IP4 192.168.1.100
s=PySIP
c=IN IP4 192.168.1.100
t=0 0
m=audio 10000 RTP/AVP 0 8 101
a=rtpmap:0 PCMU/8000
a=rtpmap:8 PCMA/8000
a=rtpmap:101 telephone-event/8000
a=fmtp:101 0-16
a=sendrecv
"""
        parser = SDPParser()
        sdp = parser.parse(sdp_data)
        
        assert sdp.version == 0
        assert sdp.connection_address == "192.168.1.100"
        assert len(sdp.media) == 1
        
        audio = sdp.audio_media
        assert audio is not None
        assert audio.port == 10000
        assert 0 in audio.formats  # PCMU
        assert 8 in audio.formats  # PCMA
    
    def test_parse_audio_address(self):
        sdp_data = b"""v=0
o=- 0 0 IN IP4 10.0.0.1
s=-
c=IN IP4 10.0.0.1
t=0 0
m=audio 12345 RTP/AVP 0
"""
        parser = SDPParser()
        sdp = parser.parse(sdp_data)
        
        addr = sdp.get_audio_address()
        assert addr == ("10.0.0.1", 12345)
    
    def test_parse_audio_codec(self):
        sdp_data = b"""v=0
o=- 0 0 IN IP4 192.168.1.1
s=-
c=IN IP4 192.168.1.1
t=0 0
m=audio 10000 RTP/AVP 0
a=rtpmap:0 PCMU/8000
"""
        parser = SDPParser()
        sdp = parser.parse(sdp_data)
        
        codec = sdp.get_audio_codec()
        assert codec is not None
        pt, name, rate = codec
        assert pt == 0
        assert name == "PCMU"
        assert rate == 8000


class TestSDPBuilder:
    """Tests for SDP building."""
    
    def test_create_offer(self):
        builder = SDPBuilder(local_ip="192.168.1.100")
        
        sdp = builder.create_offer(audio_port=10000)
        
        assert sdp.connection_address == "192.168.1.100"
        assert len(sdp.media) == 1
        assert sdp.media[0].port == 10000
    
    def test_create_answer(self):
        # Create offer first
        builder = SDPBuilder(local_ip="192.168.1.100")
        offer = builder.create_offer(audio_port=10000)
        
        # Create answer
        answer_builder = SDPBuilder(local_ip="192.168.1.200")
        answer = answer_builder.create_answer(offer, audio_port=20000)
        
        assert answer.connection_address == "192.168.1.200"
        assert answer.media[0].port == 20000
    
    def test_serialize(self):
        builder = SDPBuilder(local_ip="192.168.1.100")
        sdp = builder.create_offer(audio_port=10000)
        
        data = builder.serialize(sdp)
        
        assert b"v=0" in data
        assert b"m=audio 10000" in data
        assert b"c=IN IP4 192.168.1.100" in data


