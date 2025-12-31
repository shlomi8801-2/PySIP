"""
G.711 A-law (PCMA) Codec

ITU-T G.711 A-law companding with numpy-based implementation.
"""

from __future__ import annotations

import numpy as np

from .base import Codec


# A-law constants
ALAW_CLIP = 32635
ALAW_SEG_MASK = 0x70
ALAW_QUANT_MASK = 0x0F


# Precomputed A-law decode table (256 entries -> int16)
_ALAW_DECODE_TABLE = np.array([
     -5504,  -5248,  -6016,  -5760,  -4480,  -4224,  -4992,  -4736,
     -7552,  -7296,  -8064,  -7808,  -6528,  -6272,  -7040,  -6784,
     -2752,  -2624,  -3008,  -2880,  -2240,  -2112,  -2496,  -2368,
     -3776,  -3648,  -4032,  -3904,  -3264,  -3136,  -3520,  -3392,
    -22016, -20992, -24064, -23040, -17920, -16896, -19968, -18944,
    -30208, -29184, -32256, -31232, -26112, -25088, -28160, -27136,
    -11008, -10496, -12032, -11520,  -8960,  -8448,  -9984,  -9472,
    -15104, -14592, -16128, -15616, -13056, -12544, -14080, -13568,
      -344,   -328,   -376,   -360,   -280,   -264,   -312,   -296,
      -472,   -456,   -504,   -488,   -408,   -392,   -440,   -424,
       -88,    -72,   -120,   -104,    -24,     -8,    -56,    -40,
      -216,   -200,   -248,   -232,   -152,   -136,   -184,   -168,
     -1376,  -1312,  -1504,  -1440,  -1120,  -1056,  -1248,  -1184,
     -1888,  -1824,  -2016,  -1952,  -1632,  -1568,  -1760,  -1696,
      -688,   -656,   -752,   -720,   -560,   -528,   -624,   -592,
      -944,   -912,  -1008,   -976,   -816,   -784,   -880,   -848,
      5504,   5248,   6016,   5760,   4480,   4224,   4992,   4736,
      7552,   7296,   8064,   7808,   6528,   6272,   7040,   6784,
      2752,   2624,   3008,   2880,   2240,   2112,   2496,   2368,
      3776,   3648,   4032,   3904,   3264,   3136,   3520,   3392,
     22016,  20992,  24064,  23040,  17920,  16896,  19968,  18944,
     30208,  29184,  32256,  31232,  26112,  25088,  28160,  27136,
     11008,  10496,  12032,  11520,   8960,   8448,   9984,   9472,
     15104,  14592,  16128,  15616,  13056,  12544,  14080,  13568,
       344,    328,    376,    360,    280,    264,    312,    296,
       472,    456,    504,    488,    408,    392,    440,    424,
        88,     72,    120,    104,     24,      8,     56,     40,
       216,    200,    248,    232,    152,    136,    184,    168,
      1376,   1312,   1504,   1440,   1120,   1056,   1248,   1184,
      1888,   1824,   2016,   1952,   1632,   1568,   1760,   1696,
       688,    656,    752,    720,    560,    528,    624,    592,
       944,    912,   1008,    976,    816,    784,    880,    848,
], dtype=np.int16)


def _build_encode_table() -> np.ndarray:
    """Build A-law encode lookup table."""
    table = np.zeros(65536, dtype=np.uint8)
    
    seg_aend = [0x1F, 0x3F, 0x7F, 0xFF, 0x1FF, 0x3FF, 0x7FF, 0xFFF]
    
    for i in range(65536):
        # Convert to signed
        sample = i if i < 32768 else i - 65536
        
        # Get sign
        mask = 0x55
        if sample >= 0:
            mask |= 0x80
        else:
            sample = -sample - 1
        
        # Clip
        if sample > ALAW_CLIP:
            sample = ALAW_CLIP
        
        # Find segment
        seg = 7
        for s in range(8):
            if sample <= seg_aend[s]:
                seg = s
                break
        
        # Calculate A-law value
        if seg >= 2:
            aval = (seg << 4) | ((sample >> (seg + 3)) & ALAW_QUANT_MASK)
        else:
            aval = (seg << 4) | ((sample >> 4) & ALAW_QUANT_MASK)
        
        table[i] = aval ^ mask
    
    return table


_ALAW_ENCODE_TABLE = _build_encode_table()


class PCMACodec(Codec):
    """
    G.711 A-law codec.
    
    Features:
    - Numpy-based vectorized encoding/decoding
    - Lookup table for maximum performance
    - RTP payload type 8
    
    Example:
        codec = PCMACodec()
        
        # Encode PCM to A-law
        pcm = np.array([0, 1000, -1000, 32000], dtype=np.int16)
        encoded = codec.encode(pcm)
        
        # Decode A-law to PCM
        decoded = codec.decode(encoded)
    """
    
    __slots__ = ()
    
    name = "PCMA"
    payload_type = 8
    clock_rate = 8000
    sample_width = 2
    channels = 1
    
    def encode(self, pcm: np.ndarray) -> bytes:
        """
        Encode PCM samples to A-law.
        
        Args:
            pcm: PCM samples as int16 numpy array
            
        Returns:
            A-law encoded bytes
        """
        # Ensure int16
        if pcm.dtype != np.int16:
            pcm = pcm.astype(np.int16)
        
        # Convert to unsigned index for table lookup
        indices = pcm.view(np.uint16)
        
        # Vectorized table lookup
        encoded = _ALAW_ENCODE_TABLE[indices]
        
        return encoded.tobytes()
    
    def decode(self, data: bytes) -> np.ndarray:
        """
        Decode A-law to PCM samples.
        
        Args:
            data: A-law encoded bytes
            
        Returns:
            PCM samples as int16 numpy array
        """
        # Convert bytes to indices
        indices = np.frombuffer(data, dtype=np.uint8)
        
        # Vectorized table lookup
        return _ALAW_DECODE_TABLE[indices].copy()
    
    @staticmethod
    def encode_sample(sample: int) -> int:
        """Encode single PCM sample to A-law byte."""
        if sample < 0:
            index = sample + 65536
        else:
            index = sample
        return int(_ALAW_ENCODE_TABLE[index])
    
    @staticmethod
    def decode_sample(alaw: int) -> int:
        """Decode single A-law byte to PCM sample."""
        return int(_ALAW_DECODE_TABLE[alaw & 0xFF])


# Module-level instance for convenience
pcma = PCMACodec()


