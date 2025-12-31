"""
SIP Digest Authentication

RFC 2617 / RFC 7616 compliant digest authentication.
"""

from __future__ import annotations

import hashlib
import random
import re
import string
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .message import SIPRequest, SIPResponse


@dataclass(slots=True)
class DigestChallenge:
    """Parsed WWW-Authenticate challenge."""
    
    realm: str
    nonce: str
    algorithm: str = "MD5"
    qop: str | None = None
    opaque: str | None = None
    stale: bool = False
    domain: str | None = None


@dataclass(slots=True)
class DigestCredentials:
    """Digest authentication credentials."""
    
    username: str
    password: str
    realm: str
    nonce: str
    uri: str
    response: str
    algorithm: str = "MD5"
    cnonce: str | None = None
    nc: str | None = None
    qop: str | None = None
    opaque: str | None = None


class DigestAuth:
    """
    Digest authentication handler.
    
    Generates Authorization headers for SIP digest authentication.
    
    Example:
        auth = DigestAuth(username="alice", password="secret")
        
        # Parse challenge from 401 response
        challenge = auth.parse_challenge(response)
        
        # Generate Authorization header
        auth_header = auth.generate_authorization(
            method="INVITE",
            uri="sip:bob@example.com",
            challenge=challenge,
        )
    """
    
    __slots__ = ("_username", "_password", "_nc_counter")
    
    def __init__(self, username: str, password: str):
        self._username = username
        self._password = password
        self._nc_counter = 0
    
    @staticmethod
    def parse_challenge(response: "SIPResponse") -> DigestChallenge:
        """
        Parse WWW-Authenticate header from 401/407 response.
        
        Args:
            response: SIP response with challenge
            
        Returns:
            Parsed DigestChallenge
            
        Raises:
            ValueError: If challenge cannot be parsed
        """
        www_auth = response.headers.get("www-authenticate", "")
        if not www_auth:
            www_auth = response.headers.get("proxy-authenticate", "")
        
        if not www_auth:
            raise ValueError("No WWW-Authenticate or Proxy-Authenticate header")
        
        # Remove "Digest " prefix
        if www_auth.lower().startswith("digest "):
            www_auth = www_auth[7:]
        
        # Parse parameters
        params = DigestAuth._parse_auth_params(www_auth)
        
        realm = params.get("realm", "")
        nonce = params.get("nonce", "")
        
        if not realm or not nonce:
            raise ValueError("Missing realm or nonce in challenge")
        
        return DigestChallenge(
            realm=realm,
            nonce=nonce,
            algorithm=params.get("algorithm", "MD5"),
            qop=params.get("qop"),
            opaque=params.get("opaque"),
            stale=params.get("stale", "").lower() == "true",
            domain=params.get("domain"),
        )
    
    @staticmethod
    def _parse_auth_params(header: str) -> dict[str, str]:
        """Parse authentication parameters from header value."""
        params: dict[str, str] = {}
        
        # Match key="value" or key=value patterns
        pattern = r'(\w+)=(?:"([^"]+)"|([^\s,]+))'
        
        for match in re.finditer(pattern, header):
            key = match.group(1).lower()
            value = match.group(2) or match.group(3)
            params[key] = value
        
        return params
    
    def generate_authorization(
        self,
        method: str,
        uri: str,
        challenge: DigestChallenge,
        body: bytes | None = None,
    ) -> str:
        """
        Generate Authorization header value.
        
        Args:
            method: SIP method (e.g., "INVITE")
            uri: Request-URI
            challenge: Parsed challenge from server
            body: Request body (for qop=auth-int)
            
        Returns:
            Authorization header value
        """
        # Increment nonce count
        self._nc_counter += 1
        nc = f"{self._nc_counter:08x}"
        
        # Generate client nonce
        cnonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        
        # Select hash algorithm
        algorithm = challenge.algorithm.upper()
        if algorithm == "MD5" or algorithm == "MD5-SESS":
            hash_func = hashlib.md5
        elif algorithm == "SHA-256" or algorithm == "SHA-256-SESS":
            hash_func = hashlib.sha256
        else:
            # Default to MD5
            hash_func = hashlib.md5
        
        def H(data: str) -> str:
            return hash_func(data.encode()).hexdigest()
        
        # Calculate HA1
        ha1 = H(f"{self._username}:{challenge.realm}:{self._password}")
        
        if algorithm.endswith("-SESS"):
            ha1 = H(f"{ha1}:{challenge.nonce}:{cnonce}")
        
        # Calculate HA2
        if challenge.qop == "auth-int" and body:
            ha2 = H(f"{method}:{uri}:{H(body.decode())}")
        else:
            ha2 = H(f"{method}:{uri}")
        
        # Calculate response
        if challenge.qop in ("auth", "auth-int"):
            response = H(f"{ha1}:{challenge.nonce}:{nc}:{cnonce}:{challenge.qop}:{ha2}")
        else:
            response = H(f"{ha1}:{challenge.nonce}:{ha2}")
        
        # Build Authorization header
        parts = [
            f'Digest username="{self._username}"',
            f'realm="{challenge.realm}"',
            f'nonce="{challenge.nonce}"',
            f'uri="{uri}"',
            f'response="{response}"',
        ]
        
        if challenge.algorithm:
            parts.append(f'algorithm={challenge.algorithm}')
        
        if challenge.qop:
            parts.append(f'qop={challenge.qop}')
            parts.append(f'nc={nc}')
            parts.append(f'cnonce="{cnonce}"')
        
        if challenge.opaque:
            parts.append(f'opaque="{challenge.opaque}"')
        
        return ", ".join(parts)
    
    def generate_credentials(
        self,
        method: str,
        uri: str,
        challenge: DigestChallenge,
        body: bytes | None = None,
    ) -> DigestCredentials:
        """
        Generate digest credentials.
        
        Similar to generate_authorization but returns structured data.
        """
        self._nc_counter += 1
        nc = f"{self._nc_counter:08x}"
        cnonce = "".join(random.choices(string.ascii_lowercase + string.digits, k=16))
        
        algorithm = challenge.algorithm.upper()
        if algorithm in ("MD5", "MD5-SESS"):
            hash_func = hashlib.md5
        elif algorithm in ("SHA-256", "SHA-256-SESS"):
            hash_func = hashlib.sha256
        else:
            hash_func = hashlib.md5
        
        def H(data: str) -> str:
            return hash_func(data.encode()).hexdigest()
        
        ha1 = H(f"{self._username}:{challenge.realm}:{self._password}")
        if algorithm.endswith("-SESS"):
            ha1 = H(f"{ha1}:{challenge.nonce}:{cnonce}")
        
        if challenge.qop == "auth-int" and body:
            ha2 = H(f"{method}:{uri}:{H(body.decode())}")
        else:
            ha2 = H(f"{method}:{uri}")
        
        if challenge.qop in ("auth", "auth-int"):
            response = H(f"{ha1}:{challenge.nonce}:{nc}:{cnonce}:{challenge.qop}:{ha2}")
        else:
            response = H(f"{ha1}:{challenge.nonce}:{ha2}")
        
        return DigestCredentials(
            username=self._username,
            password=self._password,
            realm=challenge.realm,
            nonce=challenge.nonce,
            uri=uri,
            response=response,
            algorithm=challenge.algorithm,
            cnonce=cnonce if challenge.qop else None,
            nc=nc if challenge.qop else None,
            qop=challenge.qop,
            opaque=challenge.opaque,
        )


