"""
DTMF Detector

Detects DTMF tones from audio (RFC 2833 + inband).
"""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable

import numpy as np

from ...protocol.rtp import DTMFEvent, DTMFType

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# DTMF frequencies (Hz)
DTMF_LOW_FREQS = [697, 770, 852, 941]
DTMF_HIGH_FREQS = [1209, 1336, 1477, 1633]

# DTMF tone matrix
DTMF_MATRIX = [
    ["1", "2", "3", "A"],
    ["4", "5", "6", "B"],
    ["7", "8", "9", "C"],
    ["*", "0", "#", "D"],
]


@dataclass(slots=True)
class DTMFDetection:
    """Detected DTMF digit."""
    
    digit: str
    confidence: float
    duration_ms: int
    timestamp: float


class DTMFDetector:
    """
    DTMF tone detector.
    
    Supports:
    - RFC 2833 telephone events (from RTP)
    - Inband audio tone detection (Goertzel algorithm)
    
    Example:
        detector = DTMFDetector()
        
        # Set up callback
        detector.on_digit(lambda digit: print(f"DTMF: {digit}"))
        
        # Process audio frames
        for frame in audio_frames:
            detector.process_audio(frame)
    """
    
    __slots__ = (
        "_sample_rate",
        "_frame_size",
        "_on_digit",
        "_current_digit",
        "_digit_start",
        "_digit_samples",
        "_last_detection",
        "_min_duration_ms",
        "_debounce_ms",
        "_goertzel_coeffs",
    )
    
    def __init__(
        self,
        sample_rate: int = 8000,
        frame_size: int = 160,
        min_duration_ms: int = 40,
        debounce_ms: int = 100,
    ):
        """
        Initialize DTMF detector.
        
        Args:
            sample_rate: Audio sample rate
            frame_size: Samples per frame
            min_duration_ms: Minimum tone duration to detect
            debounce_ms: Debounce time between detections
        """
        self._sample_rate = sample_rate
        self._frame_size = frame_size
        self._min_duration_ms = min_duration_ms
        self._debounce_ms = debounce_ms
        
        self._on_digit: Callable[[str], None] | None = None
        self._current_digit: str | None = None
        self._digit_start: float = 0
        self._digit_samples = 0
        self._last_detection: float = 0
        
        # Pre-compute Goertzel coefficients
        self._goertzel_coeffs = self._compute_goertzel_coeffs()
    
    def _compute_goertzel_coeffs(self) -> dict[int, float]:
        """Compute Goertzel filter coefficients for DTMF frequencies."""
        coeffs = {}
        
        for freq in DTMF_LOW_FREQS + DTMF_HIGH_FREQS:
            k = int(0.5 + (self._frame_size * freq) / self._sample_rate)
            w = (2 * np.pi * k) / self._frame_size
            coeffs[freq] = 2 * np.cos(w)
        
        return coeffs
    
    def on_digit(self, callback: Callable[[str], None]) -> None:
        """Set digit detection callback."""
        self._on_digit = callback
    
    def process_rfc2833(self, event: DTMFEvent) -> str | None:
        """
        Process RFC 2833 DTMF event.
        
        Args:
            event: Parsed DTMF event
            
        Returns:
            Detected digit or None
        """
        if event.end:
            digit = event.digit
            
            # Debounce
            import time
            now = time.time()
            if now - self._last_detection < self._debounce_ms / 1000:
                return None
            
            self._last_detection = now
            
            if self._on_digit:
                self._on_digit(digit)
            
            return digit
        
        return None
    
    def process_audio(self, samples: np.ndarray) -> str | None:
        """
        Process audio frame for inband DTMF.
        
        Uses Goertzel algorithm for efficient frequency detection.
        
        Args:
            samples: Audio samples (int16)
            
        Returns:
            Detected digit or None
        """
        if samples.dtype != np.float64:
            samples = samples.astype(np.float64) / 32768.0
        
        # Detect frequencies using Goertzel
        low_idx, low_power = self._detect_frequency(samples, DTMF_LOW_FREQS)
        high_idx, high_power = self._detect_frequency(samples, DTMF_HIGH_FREQS)
        
        # Check if valid DTMF
        if low_idx >= 0 and high_idx >= 0:
            digit = DTMF_MATRIX[low_idx][high_idx]
            
            if self._current_digit == digit:
                # Continue existing digit
                self._digit_samples += len(samples)
            else:
                # New digit
                self._current_digit = digit
                self._digit_samples = len(samples)
                import time
                self._digit_start = time.time()
        else:
            # No DTMF detected
            if self._current_digit:
                # Check if we had a valid digit
                duration_ms = (self._digit_samples * 1000) // self._sample_rate
                
                if duration_ms >= self._min_duration_ms:
                    digit = self._current_digit
                    self._current_digit = None
                    self._digit_samples = 0
                    
                    # Debounce
                    import time
                    now = time.time()
                    if now - self._last_detection >= self._debounce_ms / 1000:
                        self._last_detection = now
                        
                        if self._on_digit:
                            self._on_digit(digit)
                        
                        return digit
                
                self._current_digit = None
                self._digit_samples = 0
        
        return None
    
    def _detect_frequency(
        self,
        samples: np.ndarray,
        frequencies: list[int],
    ) -> tuple[int, float]:
        """
        Detect strongest frequency in list using Goertzel.
        
        Returns:
            (index of strongest frequency, power level)
            or (-1, 0) if none detected
        """
        powers = []
        
        for freq in frequencies:
            coeff = self._goertzel_coeffs[freq]
            power = self._goertzel(samples, coeff)
            powers.append(power)
        
        max_power = max(powers)
        
        # Check if above threshold
        threshold = 0.01  # Adjust based on testing
        
        if max_power > threshold:
            # Check twist (difference between frequencies)
            avg_power = sum(powers) / len(powers)
            if max_power > avg_power * 2:  # Dominant frequency
                return powers.index(max_power), max_power
        
        return -1, 0.0
    
    def _goertzel(self, samples: np.ndarray, coeff: float) -> float:
        """Goertzel algorithm for single frequency detection."""
        s0 = 0.0
        s1 = 0.0
        s2 = 0.0
        
        for sample in samples:
            s0 = sample + coeff * s1 - s2
            s2 = s1
            s1 = s0
        
        # Calculate power
        power = s1 * s1 + s2 * s2 - coeff * s1 * s2
        return power / len(samples)


class AsyncDTMFDetector(DTMFDetector):
    """
    Async DTMF detector with event-based notification.
    """
    
    __slots__ = ("_digit_queue", "_async_callback")
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._digit_queue: asyncio.Queue[str] = asyncio.Queue()
        self._async_callback: Callable[[str], None] | None = None
        
        # Override sync callback to also enqueue
        super().on_digit(self._on_digit_sync)
    
    def _on_digit_sync(self, digit: str) -> None:
        """Internal callback to enqueue digit."""
        try:
            self._digit_queue.put_nowait(digit)
        except asyncio.QueueFull:
            pass
        
        if self._async_callback:
            self._async_callback(digit)
    
    async def get_digit(self, timeout: float | None = None) -> str | None:
        """
        Wait for next DTMF digit.
        
        Args:
            timeout: Maximum wait time
            
        Returns:
            Digit or None on timeout
        """
        try:
            if timeout:
                return await asyncio.wait_for(
                    self._digit_queue.get(),
                    timeout=timeout,
                )
            else:
                return await self._digit_queue.get()
        except asyncio.TimeoutError:
            return None
    
    async def gather(
        self,
        max_digits: int = 1,
        timeout: float = 5.0,
        finish_on_key: str | None = "#",
    ) -> str:
        """
        Gather multiple DTMF digits.
        
        Args:
            max_digits: Maximum digits to collect
            timeout: Total timeout
            finish_on_key: Key to end early
            
        Returns:
            Collected digits string
        """
        digits = []
        deadline = asyncio.get_running_loop().time() + timeout
        
        while len(digits) < max_digits:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                break
            
            digit = await self.get_digit(timeout=remaining)
            if digit is None:
                break
            
            if finish_on_key and digit == finish_on_key:
                break
            
            digits.append(digit)
        
        return "".join(digits)


