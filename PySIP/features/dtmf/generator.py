"""
DTMF Generator

Generates DTMF tones for RTP transmission.
"""

from __future__ import annotations

import numpy as np

from ...protocol.rtp.dtmf import CHAR_TO_DTMF, DTMFEvent, DTMFEventStream


# DTMF frequencies (Hz)
DTMF_FREQS = {
    "1": (697, 1209), "2": (697, 1336), "3": (697, 1477), "A": (697, 1633),
    "4": (770, 1209), "5": (770, 1336), "6": (770, 1477), "B": (770, 1633),
    "7": (852, 1209), "8": (852, 1336), "9": (852, 1477), "C": (852, 1633),
    "*": (941, 1209), "0": (941, 1336), "#": (941, 1477), "D": (941, 1633),
}


class DTMFGenerator:
    """
    DTMF tone generator.
    
    Supports:
    - RFC 2833 telephone events
    - Inband audio tones
    
    Example:
        generator = DTMFGenerator()
        
        # RFC 2833 events
        for payload in generator.generate_rfc2833("5"):
            rtp_session.send(payload, marker=first)
        
        # Inband audio
        audio = generator.generate_inband("123#")
    """
    
    __slots__ = (
        "_sample_rate",
        "_tone_duration_ms",
        "_gap_duration_ms",
        "_amplitude",
    )
    
    def __init__(
        self,
        sample_rate: int = 8000,
        tone_duration_ms: int = 100,
        gap_duration_ms: int = 50,
        amplitude: float = 0.8,
    ):
        """
        Initialize DTMF generator.
        
        Args:
            sample_rate: Audio sample rate
            tone_duration_ms: Tone duration in ms
            gap_duration_ms: Gap between tones in ms
            amplitude: Tone amplitude (0-1)
        """
        self._sample_rate = sample_rate
        self._tone_duration_ms = tone_duration_ms
        self._gap_duration_ms = gap_duration_ms
        self._amplitude = amplitude
    
    def generate_rfc2833(
        self,
        digit: str,
        duration_ms: int | None = None,
        payload_type: int = 101,
    ) -> list[tuple[bytes, bool]]:
        """
        Generate RFC 2833 DTMF event packets.
        
        Args:
            digit: DTMF digit to generate
            duration_ms: Tone duration
            payload_type: RTP payload type
            
        Returns:
            List of (payload_bytes, is_first_packet) tuples
        """
        duration = duration_ms or self._tone_duration_ms
        stream = DTMFEventStream(
            payload_type=payload_type,
            clock_rate=self._sample_rate,
        )
        return stream.generate_digit(digit, duration_ms=duration)
    
    def generate_inband(
        self,
        digits: str,
        tone_duration_ms: int | None = None,
        gap_duration_ms: int | None = None,
    ) -> np.ndarray:
        """
        Generate inband DTMF audio tones.
        
        Args:
            digits: DTMF digits to generate
            tone_duration_ms: Tone duration
            gap_duration_ms: Gap between tones
            
        Returns:
            Audio samples (int16)
        """
        tone_ms = tone_duration_ms or self._tone_duration_ms
        gap_ms = gap_duration_ms or self._gap_duration_ms
        
        samples_per_tone = (self._sample_rate * tone_ms) // 1000
        samples_per_gap = (self._sample_rate * gap_ms) // 1000
        
        audio = []
        
        for i, digit in enumerate(digits):
            if digit.upper() not in DTMF_FREQS:
                continue
            
            # Add gap before (except first digit)
            if i > 0:
                audio.append(np.zeros(samples_per_gap, dtype=np.float64))
            
            # Generate tone
            tone = self._generate_tone(digit, samples_per_tone)
            audio.append(tone)
        
        if not audio:
            return np.array([], dtype=np.int16)
        
        # Concatenate and convert to int16
        combined = np.concatenate(audio)
        return (combined * 32767 * self._amplitude).astype(np.int16)
    
    def generate_tone(self, digit: str, duration_ms: int | None = None) -> np.ndarray:
        """
        Generate single DTMF tone.
        
        Args:
            digit: DTMF digit
            duration_ms: Duration
            
        Returns:
            Audio samples (int16)
        """
        duration = duration_ms or self._tone_duration_ms
        samples = (self._sample_rate * duration) // 1000
        
        tone = self._generate_tone(digit, samples)
        return (tone * 32767 * self._amplitude).astype(np.int16)
    
    def _generate_tone(self, digit: str, num_samples: int) -> np.ndarray:
        """Generate raw tone samples (float)."""
        digit = digit.upper()
        
        if digit not in DTMF_FREQS:
            return np.zeros(num_samples, dtype=np.float64)
        
        low_freq, high_freq = DTMF_FREQS[digit]
        
        t = np.arange(num_samples, dtype=np.float64) / self._sample_rate
        
        # Generate dual-tone
        low_tone = np.sin(2 * np.pi * low_freq * t)
        high_tone = np.sin(2 * np.pi * high_freq * t)
        
        # Mix with equal amplitude
        return (low_tone + high_tone) / 2


def generate_dtmf_audio(
    digits: str,
    sample_rate: int = 8000,
    tone_duration_ms: int = 100,
    gap_duration_ms: int = 50,
) -> bytes:
    """
    Convenience function to generate DTMF audio.
    
    Args:
        digits: DTMF digits
        sample_rate: Sample rate
        tone_duration_ms: Tone duration
        gap_duration_ms: Gap duration
        
    Returns:
        PCM audio bytes (int16)
    """
    generator = DTMFGenerator(
        sample_rate=sample_rate,
        tone_duration_ms=tone_duration_ms,
        gap_duration_ms=gap_duration_ms,
    )
    audio = generator.generate_inband(digits)
    return audio.tobytes()


