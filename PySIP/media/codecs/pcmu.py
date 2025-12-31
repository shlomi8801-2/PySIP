"""
G.711 μ-law (PCMU) Codec

ITU-T G.711 μ-law companding with numpy-based implementation.
"""

from __future__ import annotations

import numpy as np

from .base import Codec


# μ-law encoding constants
MULAW_BIAS = 33
MULAW_MAX = 0x1FFF  # 8191
MULAW_CLIP = 32635


# Precomputed μ-law decode table (256 entries -> int16)
# Each μ-law byte decodes to a 14-bit value, sign-extended to 16-bit
_MULAW_DECODE_TABLE = np.array([
    -32124, -31100, -30076, -29052, -28028, -27004, -25980, -24956,
    -23932, -22908, -21884, -20860, -19836, -18812, -17788, -16764,
    -15996, -15484, -14972, -14460, -13948, -13436, -12924, -12412,
    -11900, -11388, -10876, -10364,  -9852,  -9340,  -8828,  -8316,
     -7932,  -7676,  -7420,  -7164,  -6908,  -6652,  -6396,  -6140,
     -5884,  -5628,  -5372,  -5116,  -4860,  -4604,  -4348,  -4092,
     -3900,  -3772,  -3644,  -3516,  -3388,  -3260,  -3132,  -3004,
     -2876,  -2748,  -2620,  -2492,  -2364,  -2236,  -2108,  -1980,
     -1884,  -1820,  -1756,  -1692,  -1628,  -1564,  -1500,  -1436,
     -1372,  -1308,  -1244,  -1180,  -1116,  -1052,   -988,   -924,
      -876,   -844,   -812,   -780,   -748,   -716,   -684,   -652,
      -620,   -588,   -556,   -524,   -492,   -460,   -428,   -396,
      -372,   -356,   -340,   -324,   -308,   -292,   -276,   -260,
      -244,   -228,   -212,   -196,   -180,   -164,   -148,   -132,
      -120,   -112,   -104,    -96,    -88,    -80,    -72,    -64,
       -56,    -48,    -40,    -32,    -24,    -16,     -8,      0,
     32124,  31100,  30076,  29052,  28028,  27004,  25980,  24956,
     23932,  22908,  21884,  20860,  19836,  18812,  17788,  16764,
     15996,  15484,  14972,  14460,  13948,  13436,  12924,  12412,
     11900,  11388,  10876,  10364,   9852,   9340,   8828,   8316,
      7932,   7676,   7420,   7164,   6908,   6652,   6396,   6140,
      5884,   5628,   5372,   5116,   4860,   4604,   4348,   4092,
      3900,   3772,   3644,   3516,   3388,   3260,   3132,   3004,
      2876,   2748,   2620,   2492,   2364,   2236,   2108,   1980,
      1884,   1820,   1756,   1692,   1628,   1564,   1500,   1436,
      1372,   1308,   1244,   1180,   1116,   1052,    988,    924,
       876,    844,    812,    780,    748,    716,    684,    652,
       620,    588,    556,    524,    492,    460,    428,    396,
       372,    356,    340,    324,    308,    292,    276,    260,
       244,    228,    212,    196,    180,    164,    148,    132,
       120,    112,    104,     96,     88,     80,     72,     64,
        56,     48,     40,     32,     24,     16,      8,      0,
], dtype=np.int16)


# Precomputed μ-law encode table (65536 entries for all int16 values)
# Maps signed 16-bit sample to μ-law byte
def _build_encode_table() -> np.ndarray:
    """Build μ-law encode lookup table."""
    table = np.zeros(65536, dtype=np.uint8)
    
    for i in range(65536):
        # Convert table index to signed 16-bit value
        sample = i if i < 32768 else i - 65536
        
        # Get sign and magnitude
        sign = 0 if sample >= 0 else 0x80
        if sample < 0:
            sample = -sample
        
        # Clip
        if sample > MULAW_CLIP:
            sample = MULAW_CLIP
        
        # Add bias
        sample = sample + MULAW_BIAS
        
        # Find segment
        exponent = 7
        exp_mask = 0x4000
        while exponent > 0 and not (sample & exp_mask):
            exponent -= 1
            exp_mask >>= 1
        
        # Build mantissa
        mantissa = (sample >> (exponent + 3)) & 0x0F
        
        # Combine into μ-law byte
        mulaw_byte = ~(sign | (exponent << 4) | mantissa) & 0xFF
        table[i] = mulaw_byte
    
    return table


_MULAW_ENCODE_TABLE = _build_encode_table()


class PCMUCodec(Codec):
    """
    G.711 μ-law codec.
    
    Features:
    - Numpy-based vectorized encoding/decoding
    - Lookup table for maximum performance
    - RTP payload type 0
    
    Example:
        codec = PCMUCodec()
        
        # Encode PCM to μ-law
        pcm = np.array([0, 1000, -1000, 32000], dtype=np.int16)
        encoded = codec.encode(pcm)
        
        # Decode μ-law to PCM
        decoded = codec.decode(encoded)
    """
    
    __slots__ = ()
    
    name = "PCMU"
    payload_type = 0
    clock_rate = 8000
    sample_width = 2
    channels = 1
    
    def encode(self, pcm: np.ndarray) -> bytes:
        """
        Encode PCM samples to μ-law.
        
        Args:
            pcm: PCM samples as int16 numpy array
            
        Returns:
            μ-law encoded bytes
        """
        # Ensure int16
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        
        # Convert to unsigned index for table lookup
        # int16 range [-32768, 32767] -> [0, 65535]
        indices = pcm.view(np.uint16)
        
        # Vectorized table lookup
        encoded = _MULAW_ENCODE_TABLE[indices]
        
        return encoded.tobytes()
    
    def decode(self, data: bytes) -> np.ndarray:
        """
        Decode μ-law to PCM samples.
        
        Args:
            data: μ-law encoded bytes
            
        Returns:
            PCM samples as int16 numpy array
        """
        # Convert bytes to indices
        indices = np.frombuffer(data, dtype=np.uint8)
        
        # Vectorized table lookup
        return _MULAW_DECODE_TABLE[indices].copy()
    
    @staticmethod
    def encode_sample(sample: int) -> int:
        """Encode single PCM sample to μ-law byte."""
        # Handle as unsigned for table lookup
        if sample < 0:
            index = sample + 65536
        else:
            index = sample
        return int(_MULAW_ENCODE_TABLE[index])
    
    @staticmethod
    def decode_sample(mulaw: int) -> int:
        """Decode single μ-law byte to PCM sample."""
        return int(_MULAW_DECODE_TABLE[mulaw & 0xFF])


# Module-level instance for convenience
pcmu = PCMUCodec()


