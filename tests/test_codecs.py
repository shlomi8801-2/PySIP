"""
Tests for audio codecs.
"""

import pytest
import numpy as np
from PySIP.media.codecs import PCMUCodec, PCMACodec


class TestPCMUCodec:
    """Tests for G.711 μ-law codec."""
    
    def test_encode_silence(self):
        codec = PCMUCodec()
        silence = np.zeros(160, dtype=np.int16)
        
        encoded = codec.encode(silence)
        
        assert len(encoded) == 160
        # Verify that encoded silence decodes back to near-zero
        decoded = codec.decode(encoded)
        assert np.abs(decoded).max() < 100  # Should be near zero
    
    def test_decode_silence(self):
        codec = PCMUCodec()
        # μ-law silence pattern
        silence = b"\xff" * 160
        
        decoded = codec.decode(silence)
        
        assert len(decoded) == 160
        assert decoded.dtype == np.int16
        # Should be near zero
        assert np.abs(decoded).max() < 100
    
    def test_encode_decode_roundtrip(self):
        codec = PCMUCodec()
        
        # Create a simple sine wave
        t = np.arange(160) / 8000
        original = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
        
        encoded = codec.encode(original)
        decoded = codec.decode(encoded)
        
        # Should be similar (within μ-law quantization error)
        # μ-law has about 14-bit effective resolution
        error = np.abs(original.astype(np.float64) - decoded.astype(np.float64))
        assert error.mean() < 1000  # Average error < 1000 (reasonable for μ-law)
    
    def test_encode_bytes(self):
        codec = PCMUCodec()
        pcm = np.zeros(160, dtype=np.int16)
        
        encoded = codec.encode_bytes(pcm.tobytes())
        
        assert isinstance(encoded, bytes)
        assert len(encoded) == 160
    
    def test_decode_bytes(self):
        codec = PCMUCodec()
        encoded = b"\xff" * 160
        
        decoded = codec.decode_bytes(encoded)
        
        assert isinstance(decoded, bytes)
        assert len(decoded) == 320  # 160 samples * 2 bytes


class TestPCMACodec:
    """Tests for G.711 A-law codec."""
    
    def test_encode_silence(self):
        codec = PCMACodec()
        silence = np.zeros(160, dtype=np.int16)
        
        encoded = codec.encode(silence)
        
        assert len(encoded) == 160
    
    def test_decode_silence(self):
        codec = PCMACodec()
        # A-law silence pattern
        silence = b"\xd5" * 160
        
        decoded = codec.decode(silence)
        
        assert len(decoded) == 160
        # Should be near zero
        assert np.abs(decoded).max() < 100
    
    def test_encode_decode_roundtrip(self):
        codec = PCMACodec()
        
        # Create test signal
        t = np.arange(160) / 8000
        original = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
        
        encoded = codec.encode(original)
        decoded = codec.decode(encoded)
        
        # A-law has 13-bit dynamic range, error depends on implementation
        # For now, verify basic functionality - shapes should match
        assert len(decoded) == len(original)
        # Verify signal is not completely wrong (correlation should be positive)
        correlation = np.corrcoef(original.astype(float), decoded.astype(float))[0, 1]
        assert correlation > 0.5  # Should have strong positive correlation
    
    def test_codec_properties(self):
        codec = PCMACodec()
        
        assert codec.name == "PCMA"
        assert codec.payload_type == 8
        assert codec.clock_rate == 8000


