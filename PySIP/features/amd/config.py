"""
AMD Configuration

Configuration options for Answering Machine Detection.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class AMDConfig:
    """
    AMD (Answering Machine Detection) configuration.
    
    Thresholds and timing parameters for detection algorithm.
    
    Attributes:
        initial_silence_ms: Max silence at start before deciding
        greeting_ms: Expected greeting duration range
        after_greeting_silence_ms: Silence after greeting
        total_analysis_ms: Total analysis time
        min_word_length_ms: Minimum word duration
        between_words_silence_ms: Max silence between words
        max_words: Max words before machine decision
        silence_threshold: Audio level for silence detection
    """
    
    # Timing (milliseconds)
    initial_silence_ms: int = 2500
    greeting_ms: tuple[int, int] = (1500, 5000)  # (min, max)
    after_greeting_silence_ms: int = 800
    total_analysis_ms: int = 5000
    
    # Word detection
    min_word_length_ms: int = 100
    between_words_silence_ms: int = 50
    max_words: int = 3
    
    # Audio thresholds
    silence_threshold: float = 256.0  # RMS threshold for silence
    voice_threshold: float = 512.0  # RMS threshold for voice
    
    @classmethod
    def default(cls) -> "AMDConfig":
        """Get default configuration."""
        return cls()
    
    @classmethod
    def aggressive(cls) -> "AMDConfig":
        """
        Aggressive detection - faster decisions.
        
        Good for high-volume dialing where speed matters.
        May have more false positives.
        """
        return cls(
            initial_silence_ms=2000,
            greeting_ms=(1000, 3000),
            after_greeting_silence_ms=500,
            total_analysis_ms=3500,
            max_words=2,
        )
    
    @classmethod
    def conservative(cls) -> "AMDConfig":
        """
        Conservative detection - more accurate.
        
        Good when accuracy is critical.
        Takes longer to decide.
        """
        return cls(
            initial_silence_ms=3000,
            greeting_ms=(2000, 7000),
            after_greeting_silence_ms=1200,
            total_analysis_ms=7000,
            max_words=5,
        )


