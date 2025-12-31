"""
Tests for SIP protocol implementation.
"""

import pytest
from PySIP.protocol.sip import (
    SIPParser,
    SIPBuilder,
    SIPRequest,
    SIPResponse,
    DigestAuth,
)
from PySIP.protocol.sip.builder import serialize_request, serialize_response
from PySIP.types import SIPMethod


class TestSIPParser:
    """Tests for SIP message parsing."""
    
    def test_parse_invite_request(self):
        data = b"""INVITE sip:bob@example.com SIP/2.0\r
Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK123\r
From: <sip:alice@example.com>;tag=abc123\r
To: <sip:bob@example.com>\r
Call-ID: call123@example.com\r
CSeq: 1 INVITE\r
Contact: <sip:alice@192.168.1.100:5060>\r
Content-Type: application/sdp\r
Content-Length: 0\r
\r
"""
        parser = SIPParser()
        msg = parser.parse(data)
        
        assert isinstance(msg, SIPRequest)
        assert msg.method == SIPMethod.INVITE
        assert msg.call_id == "call123@example.com"
        assert msg.from_tag == "abc123"
    
    def test_parse_200_ok_response(self):
        data = b"""SIP/2.0 200 OK\r
Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK123\r
From: <sip:alice@example.com>;tag=abc123\r
To: <sip:bob@example.com>;tag=def456\r
Call-ID: call123@example.com\r
CSeq: 1 INVITE\r
Contact: <sip:bob@192.168.1.200:5060>\r
Content-Length: 0\r
\r
"""
        parser = SIPParser()
        msg = parser.parse(data)
        
        assert isinstance(msg, SIPResponse)
        assert msg.status_code == 200
        assert msg.reason_phrase == "OK"
        assert msg.is_success
        assert msg.to_tag == "def456"
    
    def test_parse_180_ringing(self):
        data = b"""SIP/2.0 180 Ringing\r
Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK123\r
From: <sip:alice@example.com>;tag=abc123\r
To: <sip:bob@example.com>\r
Call-ID: call123\r
CSeq: 1 INVITE\r
Content-Length: 0\r
\r
"""
        parser = SIPParser()
        msg = parser.parse(data)
        
        assert isinstance(msg, SIPResponse)
        assert msg.status_code == 180
        assert msg.is_provisional
        assert not msg.is_final
    
    def test_parse_401_unauthorized(self):
        data = b"""SIP/2.0 401 Unauthorized\r
Via: SIP/2.0/UDP 192.168.1.100:5060;branch=z9hG4bK123\r
From: <sip:alice@example.com>;tag=abc123\r
To: <sip:alice@example.com>\r
Call-ID: reg123\r
CSeq: 1 REGISTER\r
WWW-Authenticate: Digest realm="example.com",nonce="abc123",algorithm=MD5\r
Content-Length: 0\r
\r
"""
        parser = SIPParser()
        msg = parser.parse(data)
        
        assert isinstance(msg, SIPResponse)
        assert msg.status_code == 401
        assert msg.is_client_error


class TestSIPBuilder:
    """Tests for SIP message building."""
    
    def test_build_invite(self):
        builder = SIPBuilder(
            local_ip="192.168.1.100",
            local_port=5060,
        )
        
        request = builder.invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
        )
        
        assert request.method == SIPMethod.INVITE
        assert request.call_id
        assert request.from_tag
    
    def test_build_register(self):
        builder = SIPBuilder(
            local_ip="192.168.1.100",
            local_port=5060,
        )
        
        request = builder.register(
            server_uri="sip:example.com",
            from_uri="sip:alice@example.com",
            expires=3600,
        )
        
        assert request.method == SIPMethod.REGISTER
        assert request.headers.get("expires") == "3600"
    
    def test_build_response(self):
        # Create a request first
        builder = SIPBuilder()
        request = builder.invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
        )
        
        # Build response
        response = builder.response(request, 200)
        
        assert response.status_code == 200
        assert response.call_id == request.call_id
    
    def test_serialize_request(self):
        builder = SIPBuilder()
        request = builder.invite(
            from_uri="sip:alice@example.com",
            to_uri="sip:bob@example.com",
        )
        
        data = serialize_request(request)
        
        assert data.startswith(b"INVITE sip:")
        assert b"SIP/2.0" in data
        assert b"\r\n\r\n" in data


class TestDigestAuth:
    """Tests for digest authentication."""
    
    def test_generate_authorization(self):
        auth = DigestAuth("alice", "secret")
        
        # Create mock challenge
        from PySIP.protocol.sip.auth import DigestChallenge
        challenge = DigestChallenge(
            realm="example.com",
            nonce="abc123def456",
            algorithm="MD5",
        )
        
        auth_header = auth.generate_authorization(
            method="REGISTER",
            uri="sip:example.com",
            challenge=challenge,
        )
        
        assert "Digest" in auth_header
        assert 'username="alice"' in auth_header
        assert 'realm="example.com"' in auth_header
        assert "response=" in auth_header


