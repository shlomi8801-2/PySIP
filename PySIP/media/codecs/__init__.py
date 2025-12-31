"""
Audio Codecs

Numpy-based G.711 codec implementations.
"""

from .base import Codec
from .pcmu import PCMUCodec
from .pcma import PCMACodec

__all__ = [
    "Codec",
    "PCMUCodec",
    "PCMACodec",
]


