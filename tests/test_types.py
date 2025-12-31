"""
Tests for types.py
"""

import pytest
from PySIP.types import (
    SIPUri,
    NameAddress,
    CallState,
    SIPMethod,
    SIPStatusCode,
)


class TestSIPUri:
    """Tests for SIPUri parsing and serialization."""
    
    def test_parse_simple_uri(self):
        uri = SIPUri.parse("sip:alice@example.com")
        assert uri.scheme == "sip"
        assert uri.user == "alice"
        assert uri.host == "example.com"
        assert uri.port is None
    
    def test_parse_uri_with_port(self):
        uri = SIPUri.parse("sip:alice@example.com:5060")
        assert uri.user == "alice"
        assert uri.host == "example.com"
        assert uri.port == 5060
    
    def test_parse_sips_uri(self):
        uri = SIPUri.parse("sips:alice@example.com")
        assert uri.scheme == "sips"
    
    def test_parse_uri_with_parameters(self):
        uri = SIPUri.parse("sip:alice@example.com;transport=tcp")
        assert uri.parameters.get("transport") == "tcp"
    
    def test_parse_uri_with_headers(self):
        uri = SIPUri.parse("sip:alice@example.com?subject=test")
        assert uri.headers.get("subject") == "test"
    
    def test_uri_to_string(self):
        uri = SIPUri(
            scheme="sip",
            user="alice",
            host="example.com",
            port=5060,
        )
        assert str(uri) == "sip:alice@example.com:5060"
    
    def test_parse_uri_with_angle_brackets(self):
        uri = SIPUri.parse("<sip:alice@example.com>")
        assert uri.user == "alice"
        assert uri.host == "example.com"


class TestNameAddress:
    """Tests for NameAddress parsing."""
    
    def test_parse_simple(self):
        na = NameAddress.parse("sip:alice@example.com")
        assert na.display_name is None
        assert na.uri.user == "alice"
    
    def test_parse_with_display_name(self):
        na = NameAddress.parse('"Alice" <sip:alice@example.com>')
        assert na.display_name == "Alice"
        assert na.uri.user == "alice"
    
    def test_parse_with_tag(self):
        na = NameAddress.parse("<sip:alice@example.com>;tag=abc123")
        assert na.parameters.get("tag") == "abc123"
    
    def test_to_string(self):
        na = NameAddress(
            display_name="Alice",
            uri=SIPUri(user="alice", host="example.com"),
            parameters={"tag": "abc123"},
        )
        result = str(na)
        assert '"Alice"' in result
        assert "sip:alice@example.com" in result


class TestEnums:
    """Tests for enum types."""
    
    def test_call_state_values(self):
        assert CallState.IDLE.name == "IDLE"
        assert CallState.ACTIVE.name == "ACTIVE"
    
    def test_sip_method_values(self):
        assert SIPMethod.INVITE.value == "INVITE"
        assert SIPMethod.BYE.value == "BYE"
    
    def test_status_code_values(self):
        assert SIPStatusCode.OK == 200
        assert SIPStatusCode.RINGING == 180
        assert SIPStatusCode.BUSY_HERE == 486


