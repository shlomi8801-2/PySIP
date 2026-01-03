"""
Call Recorder

Records call audio to file or memory.
"""

from __future__ import annotations

import asyncio
import io
import logging
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

from ...exceptions import RecordingError
from ...media.stream import AudioStream, TELEPHONY_FORMAT

if TYPE_CHECKING:
    from ...call import Call

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Recording:
    """
    Recorded audio data.
    
    Contains PCM audio and metadata.
    """
    
    audio: bytes
    duration_ms: int
    sample_rate: int = 8000
    sample_width: int = 2
    channels: int = 1
    start_time: float = field(default_factory=time.time)
    end_time: float | None = None
    
    @property
    def duration_seconds(self) -> float:
        """Duration in seconds."""
        return self.duration_ms / 1000
    
    def to_stream(self) -> AudioStream:
        """Convert to AudioStream."""
        return AudioStream(self.audio, TELEPHONY_FORMAT)
    
    def save(self, path: str | Path, format: str = "wav") -> None:
        """
        Save recording to file.
        
        Args:
            path: Output file path
            format: File format (wav, raw)
        """
        path = Path(path)
        
        if format == "wav":
            with wave.open(str(path), "wb") as wav:
                wav.setnchannels(self.channels)
                wav.setsampwidth(self.sample_width)
                wav.setframerate(self.sample_rate)
                wav.writeframes(self.audio)
        
        elif format == "raw":
            path.write_bytes(self.audio)
        
        else:
            raise RecordingError(f"Unsupported format: {format}")
    
    def to_numpy(self) -> np.ndarray:
        """Convert to numpy array."""
        return np.frombuffer(self.audio, dtype=np.int16)


class CallRecorder:
    """
    Call audio recorder.
    
    Records incoming and outgoing audio from a call.
    
    Example:
        recorder = CallRecorder()
        
        # Record call
        recording = await recorder.record(call, max_duration=60)
        
        # Save to file
        recording.save("call_recording.wav")
    """
    
    __slots__ = (
        "_sample_rate",
        "_max_size_mb",
        "_codec",
    )
    
    def __init__(
        self,
        sample_rate: int = 8000,
        max_size_mb: float = 10.0,
    ):
        """
        Initialize recorder.
        
        Args:
            sample_rate: Recording sample rate
            max_size_mb: Maximum recording size in MB
        """
        self._sample_rate = sample_rate
        self._max_size_mb = max_size_mb
        self._codec = None
    
    async def record(
        self,
        call: "Call",
        max_duration: float = 60.0,
        silence_timeout: float | None = None,
        on_audio: asyncio.Callable[[bytes], None] | None = None,
    ) -> Recording:
        """
        Record call audio.
        
        Args:
            call: Active call to record
            max_duration: Maximum recording duration in seconds
            silence_timeout: Stop after this much silence (None = no limit)
            on_audio: Optional callback for each audio frame
            
        Returns:
            Recording object with audio data
        """
        audio_chunks: list[bytes] = []
        start_time = time.time()
        last_voice_time = start_time
        
        # Calculate limits
        max_bytes = int(self._max_size_mb * 1024 * 1024)
        bytes_recorded = 0
        
        # Event to signal stop
        stop_event = asyncio.Event()
        
        # Get the call's negotiated codec (set during SDP negotiation)
        # Falls back to PCMU if not set
        call_codec = call._codec
        if call_codec is None:
            from ...media.codecs import PCMUCodec
            call_codec = PCMUCodec()
        
        def on_rtp_packet(data: bytes, addr) -> None:
            nonlocal bytes_recorded, last_voice_time
            
            if stop_event.is_set():
                return
            
            # Extract payload (skip RTP header)
            payload = data[12:] if len(data) > 12 else data
            
            # Decode using the call's negotiated codec
            try:
                pcm = call_codec.decode(payload)
                pcm_bytes = pcm.tobytes()
                
                audio_chunks.append(pcm_bytes)
                bytes_recorded += len(pcm_bytes)
                
                # Check for voice (simple RMS check)
                rms = np.sqrt(np.mean(pcm.astype(np.float64) ** 2))
                if rms > 256:  # Voice threshold
                    last_voice_time = time.time()
                
                # Callback
                if on_audio:
                    on_audio(pcm_bytes)
                
                # Check limits
                if bytes_recorded >= max_bytes:
                    logger.warning("Recording size limit reached")
                    stop_event.set()
            
            except Exception as e:
                logger.debug(f"Recording decode error: {e}")
        
        # Hook into RTP session
        old_callback = None
        if call._rtp_session:
            old_callback = call._rtp_session._on_packet
            call._rtp_session.on_packet(on_rtp_packet)
        
        try:
            # Record until conditions met
            while not stop_event.is_set():
                # Check duration
                elapsed = time.time() - start_time
                if elapsed >= max_duration:
                    logger.debug("Recording max duration reached")
                    break
                
                # Check silence timeout
                if silence_timeout:
                    silence_duration = time.time() - last_voice_time
                    if silence_duration >= silence_timeout:
                        logger.debug("Recording silence timeout")
                        break
                
                # Check call state
                if not call.is_active:
                    logger.debug("Call ended during recording")
                    break
                
                await asyncio.sleep(0.1)
        
        finally:
            # Restore callback
            if call._rtp_session and old_callback:
                call._rtp_session.on_packet(old_callback)
        
        # Combine audio
        if audio_chunks:
            audio = b"".join(audio_chunks)
        else:
            audio = b""
        
        duration_ms = int((time.time() - start_time) * 1000)
        
        return Recording(
            audio=audio,
            duration_ms=duration_ms,
            sample_rate=self._sample_rate,
            sample_width=2,
            channels=1,
            start_time=start_time,
            end_time=time.time(),
        )
    
    async def record_to_file(
        self,
        call: "Call",
        path: str | Path,
        max_duration: float = 60.0,
        **kwargs,
    ) -> Recording:
        """
        Record call directly to file.
        
        Writes audio as it's received for memory efficiency.
        
        Args:
            call: Active call to record
            path: Output file path
            max_duration: Maximum duration
            **kwargs: Additional options for record()
            
        Returns:
            Recording metadata
        """
        path = Path(path)
        
        # Open WAV file for streaming write
        wav_file = wave.open(str(path), "wb")
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(self._sample_rate)
        
        frames_written = 0
        
        def write_audio(pcm_bytes: bytes) -> None:
            nonlocal frames_written
            wav_file.writeframes(pcm_bytes)
            frames_written += len(pcm_bytes) // 2
        
        try:
            recording = await self.record(
                call,
                max_duration=max_duration,
                on_audio=write_audio,
                **kwargs,
            )
            
            return recording
        
        finally:
            wav_file.close()


class StereoRecorder(CallRecorder):
    """
    Stereo call recorder.
    
    Records incoming and outgoing audio to separate channels.
    """
    
    __slots__ = ()
    
    async def record_stereo(
        self,
        call: "Call",
        max_duration: float = 60.0,
    ) -> Recording:
        """
        Record call in stereo.
        
        Left channel: outgoing audio
        Right channel: incoming audio
        
        Note: This is a simplified implementation.
        Full stereo recording requires capturing both
        send and receive audio streams.
        """
        # For now, just do mono recording
        # Full stereo would require hooking into both
        # audio player output and RTP input
        return await self.record(call, max_duration)


