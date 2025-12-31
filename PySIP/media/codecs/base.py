"""
Audio Codec Base

Abstract base class for audio codecs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import numpy as np


class Codec(ABC):
    """
    Abstract base class for audio codecs.
    
    All codecs operate on numpy arrays for efficient processing.
    
    Subclasses must implement:
    - encode: Convert PCM samples to codec format
    - decode: Convert codec format to PCM samples
    """
    
    __slots__ = ()
    
    # Codec metadata
    name: str = "unknown"
    payload_type: int = 0
    clock_rate: int = 8000
    sample_width: int = 2  # bytes per sample
    channels: int = 1
    
    @abstractmethod
    def encode(self, pcm: np.ndarray) -> bytes:
        """
        Encode PCM samples to codec format.
        
        Args:
            pcm: PCM samples as int16 numpy array
            
        Returns:
            Encoded bytes
        """
        ...
    
    @abstractmethod
    def decode(self, data: bytes) -> np.ndarray:
        """
        Decode codec format to PCM samples.
        
        Args:
            data: Encoded bytes
            
        Returns:
            PCM samples as int16 numpy array
        """
        ...
    
    def encode_bytes(self, pcm_bytes: bytes) -> bytes:
        """
        Encode PCM bytes to codec format.
        
        Convenience method for raw bytes input.
        
        Args:
            pcm_bytes: PCM samples as raw bytes (int16 LE)
            
        Returns:
            Encoded bytes
        """
        pcm = np.frombuffer(pcm_bytes, dtype=np.int16)
        return self.encode(pcm)
    
    def decode_bytes(self, data: bytes) -> bytes:
        """
        Decode codec format to PCM bytes.
        
        Convenience method for raw bytes output.
        
        Args:
            data: Encoded bytes
            
        Returns:
            PCM samples as raw bytes (int16 LE)
        """
        pcm = self.decode(data)
        return pcm.tobytes()
    
    @property
    def samples_per_frame(self) -> int:
        """Samples per 20ms frame at clock rate."""
        return (self.clock_rate * 20) // 1000
    
    @property
    def frame_size(self) -> int:
        """Encoded frame size in bytes (for 20ms)."""
        # Override in subclasses if different
        return self.samples_per_frame
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(PT={self.payload_type}, rate={self.clock_rate})"


