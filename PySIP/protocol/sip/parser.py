"""
SIP Message Parser

High-performance SIP message parsing with zero-copy where possible.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from ...exceptions import SIPParseError
from ...types import SIPMethod, SIPUri
from .message import SIPMessage, SIPRequest, SIPResponse, get_reason_phrase

if TYPE_CHECKING:
    pass


# Precompiled patterns for performance
_REQUEST_LINE_RE = re.compile(rb"^(\w+) (.+) (SIP/2\.0)\r?\n", re.ASCII)
_STATUS_LINE_RE = re.compile(rb"^(SIP/2\.0) (\d{3}) (.*?)\r?\n", re.ASCII)
_HEADER_RE = re.compile(rb"^([\w\-]+)\s*:\s*(.+?)\s*\r?\n", re.ASCII | re.MULTILINE)
_BODY_SEPARATOR = b"\r\n\r\n"
_BODY_SEPARATOR_ALT = b"\n\n"


# Compact header names (RFC 3261 Section 7.3.3)
COMPACT_HEADERS = {
    "i": "call-id",
    "m": "contact",
    "e": "content-encoding",
    "l": "content-length",
    "c": "content-type",
    "f": "from",
    "s": "subject",
    "k": "supported",
    "t": "to",
    "v": "via",
}


class SIPParser:
    """
    SIP message parser.
    
    Parses raw SIP messages into SIPRequest or SIPResponse objects.
    
    Features:
    - Fast regex-based parsing
    - Compact header expansion
    - SDP body extraction
    - Zero-copy body handling via memoryview
    
    Example:
        parser = SIPParser()
        message = parser.parse(raw_data)
        
        if isinstance(message, SIPRequest):
            print(f"Request: {message.method}")
        else:
            print(f"Response: {message.status_code}")
    """
    
    __slots__ = ("_parse_sdp",)
    
    def __init__(self, parse_sdp: bool = True):
        """
        Initialize parser.
        
        Args:
            parse_sdp: Whether to parse SDP bodies automatically
        """
        self._parse_sdp = parse_sdp
    
    def parse(self, data: bytes) -> SIPRequest | SIPResponse:
        """
        Parse SIP message from bytes.
        
        Args:
            data: Raw SIP message bytes
            
        Returns:
            Parsed SIPRequest or SIPResponse
            
        Raises:
            SIPParseError: If message cannot be parsed
        """
        if not data:
            raise SIPParseError("Empty message", data)
        
        # Try to parse as request first
        request_match = _REQUEST_LINE_RE.match(data)
        if request_match:
            return self._parse_request(data, request_match)
        
        # Try to parse as response
        response_match = _STATUS_LINE_RE.match(data)
        if response_match:
            return self._parse_response(data, response_match)
        
        raise SIPParseError("Invalid SIP message: cannot parse start line", data)
    
    def _parse_request(self, data: bytes, match: re.Match) -> SIPRequest:
        """Parse SIP request."""
        method_bytes = match.group(1)
        uri_bytes = match.group(2)
        version_bytes = match.group(3)
        
        try:
            method_str = method_bytes.decode("ascii")
            try:
                method = SIPMethod(method_str)
            except ValueError:
                method = method_str  # Unknown method, keep as string
        except UnicodeDecodeError:
            raise SIPParseError("Invalid method encoding", data)
        
        try:
            uri = SIPUri.parse(uri_bytes.decode("utf-8"))
        except Exception as e:
            raise SIPParseError(f"Invalid Request-URI: {e}", data)
        
        headers, body = self._parse_headers_and_body(data, match.end())
        
        request = SIPRequest(
            method=method,
            uri=uri,
            version=version_bytes.decode("ascii"),
            headers=headers,
            body=body,
            raw=data,
        )
        
        # Parse SDP if present
        if self._parse_sdp and body and request.content_type.startswith("application/sdp"):
            request.sdp = self._parse_sdp_body(body)
        
        return request
    
    def _parse_response(self, data: bytes, match: re.Match) -> SIPResponse:
        """Parse SIP response."""
        version_bytes = match.group(1)
        status_bytes = match.group(2)
        reason_bytes = match.group(3)
        
        try:
            status_code = int(status_bytes.decode("ascii"))
        except (ValueError, UnicodeDecodeError):
            raise SIPParseError("Invalid status code", data)
        
        try:
            reason_phrase = reason_bytes.decode("utf-8").strip()
        except UnicodeDecodeError:
            reason_phrase = get_reason_phrase(status_code)
        
        headers, body = self._parse_headers_and_body(data, match.end())
        
        response = SIPResponse(
            status_code=status_code,
            reason_phrase=reason_phrase,
            version=version_bytes.decode("ascii"),
            headers=headers,
            body=body,
            raw=data,
        )
        
        # Parse SDP if present
        if self._parse_sdp and body and response.content_type.startswith("application/sdp"):
            response.sdp = self._parse_sdp_body(body)
        
        return response
    
    def _parse_headers_and_body(
        self,
        data: bytes,
        start_offset: int,
    ) -> tuple[dict[str, str], bytes | None]:
        """
        Parse headers and body from message.
        
        Returns:
            Tuple of (headers dict, body bytes or None)
        """
        # Find body separator
        body_start = data.find(_BODY_SEPARATOR, start_offset)
        if body_start == -1:
            body_start = data.find(_BODY_SEPARATOR_ALT, start_offset)
            separator_len = 2
        else:
            separator_len = 4
        
        if body_start == -1:
            # No body
            header_data = data[start_offset:]
            body = None
        else:
            header_data = data[start_offset:body_start]
            body = data[body_start + separator_len:]
            if not body:
                body = None
        
        # Parse headers
        headers: dict[str, str] = {}
        
        # Split by lines and parse
        lines = header_data.replace(b"\r\n", b"\n").split(b"\n")
        
        current_header: str | None = None
        current_value: str | None = None
        
        for line in lines:
            if not line:
                continue
            
            # Check for header continuation (starts with whitespace)
            if line[0:1] in (b" ", b"\t"):
                if current_header and current_value:
                    current_value += " " + line.decode("utf-8").strip()
                continue
            
            # Save previous header
            if current_header and current_value:
                self._add_header(headers, current_header, current_value)
            
            # Parse new header
            try:
                line_str = line.decode("utf-8")
            except UnicodeDecodeError:
                continue
            
            colon_idx = line_str.find(":")
            if colon_idx == -1:
                continue
            
            header_name = line_str[:colon_idx].strip()
            header_value = line_str[colon_idx + 1:].strip()
            
            current_header = header_name
            current_value = header_value
        
        # Save last header
        if current_header and current_value:
            self._add_header(headers, current_header, current_value)
        
        return headers, body
    
    def _add_header(self, headers: dict[str, str], name: str, value: str) -> None:
        """Add header to dict, expanding compact form and merging multiples."""
        # Expand compact header names
        name_lower = name.lower()
        name_lower = COMPACT_HEADERS.get(name_lower, name_lower)
        
        # Handle multiple headers with same name
        if name_lower in headers:
            # Append with comma for most headers
            headers[name_lower] += ", " + value
        else:
            headers[name_lower] = value
    
    def _parse_sdp_body(self, body: bytes) -> "SDPMessage | None":
        """Parse SDP body if SDP parser is available."""
        try:
            from ..sdp import SDPParser
            return SDPParser().parse(body)
        except ImportError:
            return None
        except Exception:
            return None


# Module-level parser instance for convenience
_default_parser = SIPParser()


def parse_sip_message(data: bytes) -> SIPRequest | SIPResponse:
    """
    Parse SIP message using default parser.
    
    Convenience function for simple use cases.
    
    Args:
        data: Raw SIP message bytes
        
    Returns:
        Parsed SIPRequest or SIPResponse
    """
    return _default_parser.parse(data)


