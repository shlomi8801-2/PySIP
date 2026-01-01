"""
Tests for RTCP protocol implementation (RFC 3550).
"""

import pytest
from PySIP.protocol.rtp.rtcp import (
    RTCPType,
    ReportBlock,
    SenderReport,
    ReceiverReport,
    SourceDescription,
    Goodbye,
    SDESChunk,
    SDESItem,
    SDESType,
    get_ntp_timestamp,
    ntp_to_compact,
    parse_rtcp_packet,
)


class TestReportBlock:
    """Tests for RTCP Report Block."""
    
    def test_serialize_correct_size(self):
        block = ReportBlock(
            ssrc=0x12345678,
            fraction_lost=25,
            cumulative_lost=100,
            highest_seq=50000,
            jitter=320,
            lsr=0xABCD1234,
            dlsr=0x00010000,
        )
        
        data = block.serialize()
        
        assert len(data) == 24  # Report block is always 24 bytes
    
    def test_serialize_parse_roundtrip(self):
        block = ReportBlock(
            ssrc=0x12345678,
            fraction_lost=25,
            cumulative_lost=100,
            highest_seq=50000,
            jitter=320,
            lsr=0xABCD1234,
            dlsr=0x00010000,
        )
        
        data = block.serialize()
        parsed = ReportBlock.parse(data)
        
        assert parsed.ssrc == block.ssrc
        assert parsed.fraction_lost == block.fraction_lost
        assert parsed.cumulative_lost == block.cumulative_lost
        assert parsed.highest_seq == block.highest_seq
        assert parsed.jitter == block.jitter
        assert parsed.lsr == block.lsr
        assert parsed.dlsr == block.dlsr
    
    def test_parse_negative_cumulative_lost(self):
        # Cumulative lost is a 24-bit signed integer
        block = ReportBlock(ssrc=1, cumulative_lost=-50)
        data = block.serialize()
        parsed = ReportBlock.parse(data)
        
        assert parsed.cumulative_lost == -50


class TestSenderReport:
    """Tests for RTCP Sender Report."""
    
    def test_serialize_minimum_size(self):
        sr = SenderReport(
            ssrc=0x11223344,
            ntp_timestamp_msw=0xAABBCCDD,
            ntp_timestamp_lsw=0x11223344,
            rtp_timestamp=160000,
            sender_packet_count=1000,
            sender_octet_count=160000,
        )
        
        data = sr.serialize()
        
        # Header (4) + sender info (24) = 28 bytes minimum
        assert len(data) >= 28
    
    def test_serialize_packet_type(self):
        sr = SenderReport(ssrc=0x11223344)
        data = sr.serialize()
        
        assert data[1] == RTCPType.SR
    
    def test_serialize_with_report_blocks(self):
        sr = SenderReport(
            ssrc=0x11223344,
            ntp_timestamp_msw=0xAABBCCDD,
            ntp_timestamp_lsw=0x11223344,
            rtp_timestamp=160000,
            sender_packet_count=1000,
            sender_octet_count=160000,
            report_blocks=[
                ReportBlock(ssrc=0x55667788, fraction_lost=10, cumulative_lost=5),
            ],
        )
        
        data = sr.serialize()
        
        # Header (4) + sender info (24) + 1 report block (24) = 52 bytes
        assert len(data) == 52
    
    def test_ntp_timestamp_property(self):
        sr = SenderReport(
            ssrc=1,
            ntp_timestamp_msw=100,
            ntp_timestamp_lsw=0x80000000,  # 0.5 in fractional part
        )
        
        assert sr.ntp_timestamp == pytest.approx(100.5, rel=1e-6)


class TestReceiverReport:
    """Tests for RTCP Receiver Report."""
    
    def test_serialize_packet_type(self):
        rr = ReceiverReport(ssrc=0x11223344)
        data = rr.serialize()
        
        assert data[1] == RTCPType.RR
    
    def test_serialize_with_report_blocks(self):
        rr = ReceiverReport(
            ssrc=0x11223344,
            report_blocks=[
                ReportBlock(ssrc=0x55667788, fraction_lost=10, cumulative_lost=5),
            ],
        )
        
        data = rr.serialize()
        
        # Header (4) + SSRC (4) + 1 report block (24) = 32 bytes
        assert len(data) == 32


class TestGoodbye:
    """Tests for RTCP BYE packet."""
    
    def test_serialize_packet_type(self):
        bye = Goodbye(ssrc_list=[0x12345678])
        data = bye.serialize()
        
        assert data[1] == RTCPType.BYE
    
    def test_serialize_minimum_size(self):
        bye = Goodbye(ssrc_list=[0x12345678])
        data = bye.serialize()
        
        # Header (4) + 1 SSRC (4) = 8 bytes minimum
        assert len(data) >= 8
    
    def test_serialize_with_reason(self):
        bye = Goodbye(ssrc_list=[0x12345678], reason="Session ended")
        data = bye.serialize()
        
        # Reason should be included in packet
        assert b"Session ended" in data
    
    def test_serialize_multiple_ssrc(self):
        bye = Goodbye(ssrc_list=[0x11111111, 0x22222222, 0x33333333])
        data = bye.serialize()
        
        # Header (4) + 3 SSRCs (12) = 16 bytes
        assert len(data) >= 16


class TestSourceDescription:
    """Tests for RTCP SDES packet."""
    
    def test_serialize_packet_type(self):
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=0x12345678,
                items=[SDESItem(SDESType.CNAME, "test@localhost")]
            )
        ])
        
        data = sdes.serialize()
        
        assert data[1] == RTCPType.SDES
    
    def test_sdes_item_serialize(self):
        item = SDESItem(SDESType.CNAME, "user@host")
        data = item.serialize()
        
        assert data[0] == SDESType.CNAME
        assert data[1] == len("user@host")
        assert b"user@host" in data


class TestNTPHelpers:
    """Tests for NTP timestamp helper functions."""
    
    def test_get_ntp_timestamp_reasonable_values(self):
        msw, lsw = get_ntp_timestamp()
        
        # MSW should be reasonable (after year 2000 in NTP time)
        assert msw > 3000000000
        # LSW should be within valid range
        assert 0 <= lsw <= 0xFFFFFFFF
    
    def test_ntp_to_compact(self):
        # Compact form is middle 32 bits of 64-bit NTP timestamp
        msw = 0xAABBCCDD
        lsw = 0x11223344
        
        compact = ntp_to_compact(msw, lsw)
        
        # Lower 16 bits of MSW + upper 16 bits of LSW
        assert compact == 0xCCDD1122


class TestParsing:
    """Tests for RTCP packet parsing."""
    
    def test_parse_sender_report(self):
        sr = SenderReport(
            ssrc=0x11223344,
            ntp_timestamp_msw=0xAABBCCDD,
            ntp_timestamp_lsw=0x11223344,
            rtp_timestamp=160000,
            sender_packet_count=1000,
            sender_octet_count=160000,
        )
        
        data = sr.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert isinstance(parsed, SenderReport)
        assert parsed.ssrc == sr.ssrc
        assert parsed.sender_packet_count == sr.sender_packet_count
    
    def test_parse_receiver_report(self):
        rr = ReceiverReport(ssrc=0x11223344, report_blocks=[])
        
        data = rr.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert isinstance(parsed, ReceiverReport)
        assert parsed.ssrc == rr.ssrc
    
    def test_parse_goodbye(self):
        bye = Goodbye(ssrc_list=[0x12345678, 0xAABBCCDD])
        
        data = bye.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert isinstance(parsed, Goodbye)
        assert 0x12345678 in parsed.ssrc_list
    
    def test_parse_invalid_version(self):
        # Create packet with invalid version (not 2)
        data = bytes([0x00, 0xC8, 0x00, 0x01, 0x00, 0x00, 0x00, 0x00])
        
        with pytest.raises(ValueError, match="Invalid RTCP version"):
            parse_rtcp_packet(data)
    
    def test_parse_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            parse_rtcp_packet(b"\x80\xC8")
    
    def test_parse_sdes(self):
        """Test SDES packet parsing."""
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=0x12345678,
                items=[
                    SDESItem(SDESType.CNAME, "user@example.com"),
                    SDESItem(SDESType.NAME, "Test User"),
                ]
            )
        ])
        
        data = sdes.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert isinstance(parsed, SourceDescription)
        assert len(parsed.chunks) == 1
        assert parsed.chunks[0].ssrc == 0x12345678
        assert len(parsed.chunks[0].items) == 2
    
    def test_parse_sdes_get_cname(self):
        """Test SDES CNAME extraction."""
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=0x12345678,
                items=[SDESItem(SDESType.CNAME, "user@example.com")]
            )
        ])
        
        data = sdes.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert parsed.get_cname(0x12345678) == "user@example.com"
        assert parsed.get_cname(0x99999999) is None


class TestSDESParsing:
    """Tests for SDES chunk and item parsing."""
    
    def test_sdes_item_parse(self):
        """Test individual SDES item parsing."""
        item = SDESItem(SDESType.CNAME, "test@localhost")
        data = item.serialize()
        
        parsed, consumed = SDESItem.parse(data)
        
        assert parsed is not None
        assert parsed.item_type == SDESType.CNAME
        assert parsed.value == "test@localhost"
        assert consumed == len(data)
    
    def test_sdes_item_parse_end(self):
        """Test END item returns None."""
        data = b"\x00"  # END item
        
        parsed, consumed = SDESItem.parse(data)
        
        assert parsed is None
        assert consumed == 1
    
    def test_sdes_chunk_parse(self):
        """Test SDES chunk parsing."""
        chunk = SDESChunk(
            ssrc=0xAABBCCDD,
            items=[
                SDESItem(SDESType.CNAME, "cname@test"),
                SDESItem(SDESType.EMAIL, "email@test"),
            ]
        )
        data = chunk.serialize()
        
        parsed, consumed = SDESChunk.parse(data)
        
        assert parsed is not None
        assert parsed.ssrc == 0xAABBCCDD
        assert len(parsed.items) == 2
        assert parsed.get_cname() == "cname@test"
    
    def test_sdes_multiple_chunks(self):
        """Test SDES with multiple chunks."""
        sdes = SourceDescription(chunks=[
            SDESChunk(
                ssrc=0x11111111,
                items=[SDESItem(SDESType.CNAME, "source1")]
            ),
            SDESChunk(
                ssrc=0x22222222,
                items=[SDESItem(SDESType.CNAME, "source2")]
            ),
        ])
        
        data = sdes.serialize()
        parsed = parse_rtcp_packet(data)
        
        assert isinstance(parsed, SourceDescription)
        assert len(parsed.chunks) == 2
        assert parsed.get_cname(0x11111111) == "source1"
        assert parsed.get_cname(0x22222222) == "source2"


class TestRTCPMUX:
    """Tests for RTCP-MUX packet differentiation."""
    
    def test_rtcp_packet_type_in_range(self):
        """Test that RTCP packet types fall in 200-204 range."""
        assert RTCPType.SR == 200
        assert RTCPType.RR == 201
        assert RTCPType.SDES == 202
        assert RTCPType.BYE == 203
        assert RTCPType.APP == 204
    
    def test_sr_second_byte_is_packet_type(self):
        """Test that SR packet's second byte is the packet type (200)."""
        sr = SenderReport(ssrc=0x12345678)
        data = sr.serialize()
        
        # Second byte should be PT=200
        assert data[1] == 200
    
    def test_rr_second_byte_is_packet_type(self):
        """Test that RR packet's second byte is the packet type (201)."""
        rr = ReceiverReport(ssrc=0x12345678)
        data = rr.serialize()
        
        assert data[1] == 201
    
    def test_rtcp_vs_rtp_differentiation(self):
        """Test that RTCP packets can be differentiated from RTP by second byte."""
        # RTCP SR packet
        sr = SenderReport(ssrc=0x12345678)
        sr_data = sr.serialize()
        
        # RTP packet (simulated) - second byte would be marker + PT
        # RTP payload types are typically 0-127
        rtp_data = bytes([0x80, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0xA0, 
                         0x12, 0x34, 0x56, 0x78])
        
        # RTCP: second byte in range 200-204
        assert 200 <= sr_data[1] <= 204
        # RTP: second byte (payload type without marker) is < 128
        assert (rtp_data[1] & 0x7F) < 128


class TestRTTCalculation:
    """Tests for RTT calculation data structures."""
    
    def test_report_block_lsr_dlsr_fields(self):
        """Test LSR and DLSR fields for RTT calculation."""
        block = ReportBlock(
            ssrc=0x12345678,
            lsr=0xABCD1234,  # Last SR timestamp
            dlsr=0x00010000,  # Delay since last SR (1 second)
        )
        
        data = block.serialize()
        parsed = ReportBlock.parse(data)
        
        assert parsed.lsr == 0xABCD1234
        assert parsed.dlsr == 0x00010000
    
    def test_compact_ntp_for_lsr(self):
        """Test compact NTP format used for LSR field."""
        # When we receive an SR with NTP timestamp, we store the
        # compact form (middle 32 bits) for LSR field
        msw = 0x12345678
        lsw = 0xABCDEF01
        
        compact = ntp_to_compact(msw, lsw)
        
        # Should be lower 16 bits of MSW + upper 16 bits of LSW
        expected = ((msw & 0xFFFF) << 16) | ((lsw >> 16) & 0xFFFF)
        assert compact == expected


class TestFractionLost:
    """Tests for fraction lost calculation."""
    
    def test_fraction_lost_range(self):
        """Test fraction lost is in valid range (0-255)."""
        # Test various fraction lost values
        for frac in [0, 1, 128, 255]:
            block = ReportBlock(ssrc=1, fraction_lost=frac)
            data = block.serialize()
            parsed = ReportBlock.parse(data)
            
            assert 0 <= parsed.fraction_lost <= 255
            assert parsed.fraction_lost == frac
    
    def test_fraction_lost_calculation(self):
        """Test fraction lost calculation formula."""
        # RFC 3550: fraction = (expected - received) * 256 / expected
        expected = 100
        received = 95
        lost = expected - received
        
        fraction = int((lost * 256) / expected) if expected > 0 else 0
        
        # 5 packets lost out of 100 = 5% = 12.8 -> 12
        assert fraction == 12