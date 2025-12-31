"""
Edge TTS Engine

Microsoft Edge TTS (free, no API key required).
"""

from __future__ import annotations

import asyncio
import io
import logging
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from ...exceptions import TTSError
from ...media.stream import AudioStream, TELEPHONY_FORMAT
from .engine import TTSEngine

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# Common voices
VOICES = {
    # English (US)
    "en-US-AriaNeural": "en-US-AriaNeural",
    "en-US-GuyNeural": "en-US-GuyNeural",
    "en-US-JennyNeural": "en-US-JennyNeural",
    # English (UK)
    "en-GB-SoniaNeural": "en-GB-SoniaNeural",
    "en-GB-RyanNeural": "en-GB-RyanNeural",
    # German
    "de-DE-KatjaNeural": "de-DE-KatjaNeural",
    "de-DE-ConradNeural": "de-DE-ConradNeural",
    # French
    "fr-FR-DeniseNeural": "fr-FR-DeniseNeural",
    "fr-FR-HenriNeural": "fr-FR-HenriNeural",
    # Spanish
    "es-ES-ElviraNeural": "es-ES-ElviraNeural",
    "es-ES-AlvaroNeural": "es-ES-AlvaroNeural",
}

DEFAULT_VOICE = "en-US-AriaNeural"


class EdgeTTSEngine(TTSEngine):
    """
    Microsoft Edge TTS engine.
    
    Uses the edge-tts library for free text-to-speech.
    
    Features:
    - No API key required
    - Many high-quality voices
    - Automatic resampling to 8kHz for telephony
    
    Example:
        engine = EdgeTTSEngine()
        audio = await engine.synthesize("Hello, caller!")
    """
    
    __slots__ = ("_default_voice", "_cache", "_cache_enabled")
    
    def __init__(
        self,
        default_voice: str = DEFAULT_VOICE,
        cache_enabled: bool = True,
    ):
        self._default_voice = default_voice
        self._cache: dict[tuple[str, str], AudioStream] = {}
        self._cache_enabled = cache_enabled
    
    @property
    def name(self) -> str:
        return "EdgeTTS"
    
    async def synthesize(
        self,
        text: str,
        voice: str | None = None,
        **kwargs,
    ) -> AudioStream:
        """
        Synthesize text to audio.
        
        Args:
            text: Text to speak
            voice: Voice name (default: en-US-AriaNeural)
            **kwargs: Additional options (rate, pitch, volume)
            
        Returns:
            AudioStream resampled to 8kHz mono
        """
        voice = voice or self._default_voice
        
        # Check cache
        cache_key = (text, voice)
        if self._cache_enabled and cache_key in self._cache:
            stream = self._cache[cache_key]
            stream.reset()
            return stream
        
        try:
            import edge_tts
        except ImportError:
            raise TTSError("edge-tts library not installed. Run: pip install edge-tts")
        
        try:
            # Create communicator
            communicate = edge_tts.Communicate(text, voice)
            
            # Generate audio to temp file
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
                temp_path = f.name
            
            await communicate.save(temp_path)
            
            # Convert MP3 to WAV and resample
            audio = await self._convert_to_telephony(temp_path)
            
            # Clean up
            Path(temp_path).unlink(missing_ok=True)
            
            # Cache result
            if self._cache_enabled:
                self._cache[cache_key] = audio
            
            return audio
        
        except Exception as e:
            logger.error(f"TTS synthesis failed: {e}")
            raise TTSError(f"TTS synthesis failed: {e}")
    
    async def _convert_to_telephony(self, mp3_path: str) -> AudioStream:
        """Convert MP3 to 8kHz mono PCM."""
        try:
            from pydub import AudioSegment
        except ImportError:
            raise TTSError("pydub library not installed. Run: pip install pydub")
        
        # Run in thread pool to avoid blocking
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            self._convert_sync,
            mp3_path,
        )
    
    def _convert_sync(self, mp3_path: str) -> AudioStream:
        """Synchronous conversion."""
        from pydub import AudioSegment
        
        # Load MP3
        audio = AudioSegment.from_mp3(mp3_path)
        
        # Convert to telephony format
        audio = audio.set_frame_rate(8000)
        audio = audio.set_channels(1)
        audio = audio.set_sample_width(2)  # 16-bit
        
        # Export to raw PCM
        pcm_data = audio.raw_data
        
        return AudioStream(pcm_data, TELEPHONY_FORMAT)
    
    async def get_voices(self) -> list[str]:
        """Get available voices."""
        try:
            import edge_tts
            voices = await edge_tts.list_voices()
            return [v["ShortName"] for v in voices]
        except ImportError:
            return list(VOICES.keys())
        except Exception:
            return list(VOICES.keys())
    
    def clear_cache(self) -> None:
        """Clear TTS cache."""
        self._cache.clear()


