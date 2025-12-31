"""
TTS Engine Base

Abstract base class for text-to-speech engines.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...media.stream import AudioStream


class TTSEngine(ABC):
    """
    Abstract base class for TTS engines.
    
    Subclasses implement specific TTS providers:
    - EdgeTTSEngine: Microsoft Edge TTS (free)
    - GoogleTTSEngine: Google Cloud TTS
    - AWSPollyEngine: Amazon Polly
    
    Example:
        engine = EdgeTTSEngine()
        audio = await engine.synthesize("Hello, world!")
        await call.play(audio)
    """
    
    __slots__ = ()
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Engine name."""
        ...
    
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        **kwargs,
    ) -> "AudioStream":
        """
        Synthesize text to audio.
        
        Args:
            text: Text to synthesize
            voice: Voice name (engine-specific)
            **kwargs: Additional engine-specific options
            
        Returns:
            AudioStream with synthesized audio
        """
        ...
    
    @abstractmethod
    async def get_voices(self) -> list[str]:
        """
        Get available voices.
        
        Returns:
            List of voice names
        """
        ...


