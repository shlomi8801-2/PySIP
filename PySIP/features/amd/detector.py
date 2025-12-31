"""
AMD Detector

Answering Machine Detection using audio analysis.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Callable

import numpy as np

from ...types import AMDResultType
from .config import AMDConfig

if TYPE_CHECKING:
    from ...call import Call

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AMDResult:
    """AMD detection result."""
    
    result: AMDResultType
    confidence: float  # 0.0 - 1.0
    duration_ms: int  # Time to detection
    greeting_length_ms: int = 0
    words_detected: int = 0
    
    @property
    def is_human(self) -> bool:
        return self.result == AMDResultType.HUMAN
    
    @property
    def is_machine(self) -> bool:
        return self.result == AMDResultType.MACHINE


class AMDState(Enum):
    """Internal AMD state machine states."""
    WAITING_VOICE = 0  # Waiting for initial voice
    ANALYZING = 1  # Analyzing voice pattern
    WAITING_SILENCE = 2  # Waiting for post-greeting silence
    COMPLETE = 3  # Detection complete


class AMDDetector:
    """
    Answering Machine Detector.
    
    Analyzes audio to determine if call was answered by
    human or machine (voicemail, IVR).
    
    Algorithm:
    1. Wait for voice activity
    2. Analyze greeting duration and word count
    3. Wait for post-greeting silence
    4. Decide based on patterns
    
    Typical patterns:
    - Human: Short greeting (< 1.5s), quick silence after
    - Machine: Long greeting (> 3s), many words, specific timing
    
    Example:
        detector = AMDDetector()
        result = await detector.detect(call)
        
        if result.is_human:
            await call.say("Hello! This is...")
        else:
            await call.hangup()
    """
    
    __slots__ = (
        "_config",
        "_state",
        "_start_time",
        "_voice_start_time",
        "_silence_start_time",
        "_words",
        "_total_voice_ms",
        "_result",
        "_audio_buffer",
        "_on_result",
    )
    
    def __init__(self, config: AMDConfig | None = None):
        """
        Initialize AMD detector.
        
        Args:
            config: Detection configuration
        """
        self._config = config or AMDConfig.default()
        self._reset()
    
    def _reset(self) -> None:
        """Reset detector state."""
        self._state = AMDState.WAITING_VOICE
        self._start_time = 0.0
        self._voice_start_time = 0.0
        self._silence_start_time = 0.0
        self._words = 0
        self._total_voice_ms = 0
        self._result: AMDResult | None = None
        self._audio_buffer: list[np.ndarray] = []
        self._on_result: Callable[[AMDResult], None] | None = None
    
    def on_result(self, callback: Callable[[AMDResult], None]) -> None:
        """Set result callback."""
        self._on_result = callback
    
    async def detect(self, call: "Call") -> AMDResult:
        """
        Run AMD detection on call.
        
        Args:
            call: Active call to analyze
            
        Returns:
            Detection result
        """
        self._reset()
        self._start_time = time.time()
        
        # Set up audio processing
        result_event = asyncio.Event()
        
        def on_audio(data: bytes, addr):
            if self._state == AMDState.COMPLETE:
                return
            
            # Decode audio
            try:
                samples = np.frombuffer(data[12:], dtype=np.uint8)
                # Simple μ-law decode approximation
                decoded = (samples.astype(np.float64) - 128) * 256
                self._process_audio(decoded)
                
                if self._result:
                    result_event.set()
            except Exception as e:
                logger.debug(f"AMD audio processing error: {e}")
        
        # Hook into RTP session
        if call._rtp_session:
            old_callback = call._rtp_session._on_packet
            call._rtp_session.on_packet(on_audio)
        
        try:
            # Wait for result or timeout
            try:
                await asyncio.wait_for(
                    result_event.wait(),
                    timeout=self._config.total_analysis_ms / 1000,
                )
            except asyncio.TimeoutError:
                # Timeout - make decision based on current state
                self._make_timeout_decision()
            
            return self._result or AMDResult(
                result=AMDResultType.NOTSURE,
                confidence=0.0,
                duration_ms=int((time.time() - self._start_time) * 1000),
            )
        
        finally:
            # Restore original callback
            if call._rtp_session and old_callback:
                call._rtp_session.on_packet(old_callback)
    
    def _process_audio(self, samples: np.ndarray) -> None:
        """Process audio frame for AMD."""
        now = time.time()
        elapsed_ms = int((now - self._start_time) * 1000)
        
        # Calculate RMS
        rms = np.sqrt(np.mean(samples ** 2))
        is_voice = rms > self._config.voice_threshold
        is_silence = rms < self._config.silence_threshold
        
        if self._state == AMDState.WAITING_VOICE:
            if is_voice:
                # Voice detected - start analyzing
                self._state = AMDState.ANALYZING
                self._voice_start_time = now
                self._words = 1
                logger.debug("AMD: Voice detected, starting analysis")
            elif elapsed_ms > self._config.initial_silence_ms:
                # Too much initial silence
                self._complete(
                    AMDResultType.SILENCE,
                    confidence=0.9,
                    duration_ms=elapsed_ms,
                )
        
        elif self._state == AMDState.ANALYZING:
            if is_voice:
                self._silence_start_time = 0
                voice_ms = int((now - self._voice_start_time) * 1000)
                
                # Check for long greeting (machine)
                if voice_ms > self._config.greeting_ms[1]:
                    self._complete(
                        AMDResultType.MACHINE,
                        confidence=0.85,
                        duration_ms=elapsed_ms,
                        greeting_length_ms=voice_ms,
                        words_detected=self._words,
                    )
            
            elif is_silence:
                if self._silence_start_time == 0:
                    self._silence_start_time = now
                
                silence_ms = int((now - self._silence_start_time) * 1000)
                
                # Short silence - might be between words
                if silence_ms > self._config.between_words_silence_ms:
                    if silence_ms < self._config.after_greeting_silence_ms:
                        # Another word coming?
                        self._words += 1
                        
                        if self._words > self._config.max_words:
                            voice_ms = int((now - self._voice_start_time) * 1000)
                            self._complete(
                                AMDResultType.MACHINE,
                                confidence=0.8,
                                duration_ms=elapsed_ms,
                                greeting_length_ms=voice_ms,
                                words_detected=self._words,
                            )
                    else:
                        # Long silence - greeting ended
                        self._state = AMDState.WAITING_SILENCE
                        voice_ms = int((self._silence_start_time - self._voice_start_time) * 1000)
                        self._total_voice_ms = voice_ms
        
        elif self._state == AMDState.WAITING_SILENCE:
            silence_ms = int((now - self._silence_start_time) * 1000)
            
            if is_voice:
                # More voice after silence - likely machine
                if silence_ms > self._config.after_greeting_silence_ms:
                    self._complete(
                        AMDResultType.MACHINE,
                        confidence=0.75,
                        duration_ms=elapsed_ms,
                        greeting_length_ms=self._total_voice_ms,
                        words_detected=self._words,
                    )
                else:
                    # Reset to analyzing
                    self._state = AMDState.ANALYZING
                    self._silence_start_time = 0
            
            elif silence_ms > self._config.after_greeting_silence_ms:
                # Enough silence after greeting
                # Short greeting = human, long = machine
                if self._total_voice_ms < self._config.greeting_ms[0]:
                    self._complete(
                        AMDResultType.HUMAN,
                        confidence=0.85,
                        duration_ms=elapsed_ms,
                        greeting_length_ms=self._total_voice_ms,
                        words_detected=self._words,
                    )
                elif self._total_voice_ms > self._config.greeting_ms[1]:
                    self._complete(
                        AMDResultType.MACHINE,
                        confidence=0.85,
                        duration_ms=elapsed_ms,
                        greeting_length_ms=self._total_voice_ms,
                        words_detected=self._words,
                    )
                else:
                    # In between - use word count
                    if self._words <= 2:
                        self._complete(
                            AMDResultType.HUMAN,
                            confidence=0.7,
                            duration_ms=elapsed_ms,
                            greeting_length_ms=self._total_voice_ms,
                            words_detected=self._words,
                        )
                    else:
                        self._complete(
                            AMDResultType.MACHINE,
                            confidence=0.7,
                            duration_ms=elapsed_ms,
                            greeting_length_ms=self._total_voice_ms,
                            words_detected=self._words,
                        )
    
    def _make_timeout_decision(self) -> None:
        """Make decision when timeout occurs."""
        elapsed_ms = int((time.time() - self._start_time) * 1000)
        
        if self._state == AMDState.WAITING_VOICE:
            self._complete(
                AMDResultType.SILENCE,
                confidence=0.9,
                duration_ms=elapsed_ms,
            )
        elif self._state in (AMDState.ANALYZING, AMDState.WAITING_SILENCE):
            # Timeout during analysis - probably machine
            self._complete(
                AMDResultType.MACHINE,
                confidence=0.6,
                duration_ms=elapsed_ms,
                greeting_length_ms=self._total_voice_ms,
                words_detected=self._words,
            )
        else:
            self._complete(
                AMDResultType.NOTSURE,
                confidence=0.0,
                duration_ms=elapsed_ms,
            )
    
    def _complete(
        self,
        result: AMDResultType,
        confidence: float,
        duration_ms: int,
        greeting_length_ms: int = 0,
        words_detected: int = 0,
    ) -> None:
        """Complete detection with result."""
        self._state = AMDState.COMPLETE
        self._result = AMDResult(
            result=result,
            confidence=confidence,
            duration_ms=duration_ms,
            greeting_length_ms=greeting_length_ms,
            words_detected=words_detected,
        )
        
        logger.info(f"AMD: {result.value} (confidence: {confidence:.2f})")
        
        if self._on_result:
            self._on_result(self._result)


