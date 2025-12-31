"""
Audio Stream

Handles audio file loading and streaming with chunked delivery.
"""

from __future__ import annotations

import asyncio
import io
import logging
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, AsyncIterator, Iterator

import numpy as np

from ..exceptions import AudioFileError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class AudioFormat:
    """Audio format specification."""
    
    sample_rate: int = 8000
    sample_width: int = 2  # bytes (16-bit)
    channels: int = 1
    
    @property
    def bytes_per_second(self) -> int:
        return self.sample_rate * self.sample_width * self.channels
    
    @property
    def bytes_per_ms(self) -> int:
        return self.bytes_per_second // 1000


# Standard telephony format
TELEPHONY_FORMAT = AudioFormat(sample_rate=8000, sample_width=2, channels=1)


class AudioStream:
    """
    Audio stream with chunked loading.
    
    Supports:
    - WAV file loading
    - Raw PCM data
    - Chunked iteration for RTP packetization
    - Async iteration
    
    Example:
        # From file
        stream = AudioStream.from_file("audio.wav")
        
        # From raw data
        stream = AudioStream(pcm_data, format=TELEPHONY_FORMAT)
        
        # Iterate in chunks
        for chunk in stream.chunks(160):  # 160 samples = 20ms @ 8kHz
            send_rtp(codec.encode(chunk))
    """
    
    __slots__ = (
        "_data",
        "_format",
        "_position",
        "_length",
    )
    
    def __init__(
        self,
        data: bytes,
        format: AudioFormat = TELEPHONY_FORMAT,
    ):
        """
        Initialize audio stream.
        
        Args:
            data: Raw PCM audio data
            format: Audio format specification
        """
        self._data = data
        self._format = format
        self._position = 0
        self._length = len(data)
    
    @classmethod
    def from_file(cls, path: str | Path) -> "AudioStream":
        """
        Load audio from WAV file.
        
        Args:
            path: Path to WAV file
            
        Returns:
            AudioStream instance
            
        Raises:
            AudioFileError: If file cannot be loaded
        """
        path = Path(path)
        
        if not path.exists():
            raise AudioFileError(str(path), "File not found")
        
        try:
            with wave.open(str(path), "rb") as wav:
                # Get format info
                channels = wav.getnchannels()
                sample_width = wav.getsampwidth()
                sample_rate = wav.getframerate()
                
                # Read all frames
                data = wav.readframes(wav.getnframes())
                
                format = AudioFormat(
                    sample_rate=sample_rate,
                    sample_width=sample_width,
                    channels=channels,
                )
                
                return cls(data, format)
        
        except wave.Error as e:
            raise AudioFileError(str(path), f"Invalid WAV file: {e}")
        except IOError as e:
            raise AudioFileError(str(path), f"Cannot read file: {e}")
    
    @classmethod
    def from_numpy(
        cls,
        samples: np.ndarray,
        sample_rate: int = 8000,
    ) -> "AudioStream":
        """
        Create stream from numpy array.
        
        Args:
            samples: Audio samples (int16)
            sample_rate: Sample rate
            
        Returns:
            AudioStream instance
        """
        if samples.dtype != np.int16:
            samples = samples.astype(np.int16)
        
        return cls(
            samples.tobytes(),
            AudioFormat(sample_rate=sample_rate, sample_width=2, channels=1),
        )
    
    @classmethod
    def silence(cls, duration_ms: int, format: AudioFormat = TELEPHONY_FORMAT) -> "AudioStream":
        """
        Create silent audio stream.
        
        Args:
            duration_ms: Duration in milliseconds
            format: Audio format
            
        Returns:
            AudioStream with silence
        """
        num_bytes = (format.bytes_per_ms * duration_ms)
        return cls(b"\x00" * num_bytes, format)
    
    @property
    def format(self) -> AudioFormat:
        """Audio format."""
        return self._format
    
    @property
    def duration_ms(self) -> int:
        """Total duration in milliseconds."""
        return (self._length * 1000) // self._format.bytes_per_second
    
    @property
    def position_ms(self) -> int:
        """Current position in milliseconds."""
        return (self._position * 1000) // self._format.bytes_per_second
    
    @property
    def remaining_ms(self) -> int:
        """Remaining duration in milliseconds."""
        return self.duration_ms - self.position_ms
    
    @property
    def is_complete(self) -> bool:
        """Check if stream is fully consumed."""
        return self._position >= self._length
    
    def reset(self) -> None:
        """Reset stream to beginning."""
        self._position = 0
    
    def seek_ms(self, position_ms: int) -> None:
        """
        Seek to position in milliseconds.
        
        Args:
            position_ms: Target position
        """
        byte_pos = (position_ms * self._format.bytes_per_second) // 1000
        # Align to sample boundary
        byte_pos = (byte_pos // self._format.sample_width) * self._format.sample_width
        self._position = max(0, min(byte_pos, self._length))
    
    def read(self, num_bytes: int) -> bytes:
        """
        Read bytes from stream.
        
        Args:
            num_bytes: Number of bytes to read
            
        Returns:
            Audio data (may be shorter at end of stream)
        """
        if self._position >= self._length:
            return b""
        
        end = min(self._position + num_bytes, self._length)
        data = self._data[self._position:end]
        self._position = end
        return data
    
    def read_samples(self, num_samples: int) -> bytes:
        """
        Read samples from stream.
        
        Args:
            num_samples: Number of samples to read
            
        Returns:
            Audio data for specified samples
        """
        return self.read(num_samples * self._format.sample_width)
    
    def read_ms(self, duration_ms: int) -> bytes:
        """
        Read milliseconds of audio.
        
        Args:
            duration_ms: Duration in milliseconds
            
        Returns:
            Audio data for specified duration
        """
        return self.read(self._format.bytes_per_ms * duration_ms)
    
    def chunks(self, samples_per_chunk: int) -> Iterator[bytes]:
        """
        Iterate over audio in fixed-size chunks.
        
        Args:
            samples_per_chunk: Samples per chunk (e.g., 160 for 20ms @ 8kHz)
            
        Yields:
            Audio data chunks
        """
        chunk_size = samples_per_chunk * self._format.sample_width
        
        while not self.is_complete:
            chunk = self.read(chunk_size)
            if chunk:
                # Pad last chunk if needed
                if len(chunk) < chunk_size:
                    chunk = chunk + b"\x00" * (chunk_size - len(chunk))
                yield chunk
    
    def chunks_ms(self, chunk_duration_ms: int) -> Iterator[bytes]:
        """
        Iterate over audio in time-based chunks.
        
        Args:
            chunk_duration_ms: Chunk duration in milliseconds
            
        Yields:
            Audio data chunks
        """
        samples_per_chunk = (self._format.sample_rate * chunk_duration_ms) // 1000
        yield from self.chunks(samples_per_chunk)
    
    async def async_chunks(
        self,
        samples_per_chunk: int,
        interval_ms: int | None = None,
    ) -> AsyncIterator[bytes]:
        """
        Async iteration with optional timing.
        
        Args:
            samples_per_chunk: Samples per chunk
            interval_ms: Optional delay between chunks
            
        Yields:
            Audio data chunks
        """
        chunk_size = samples_per_chunk * self._format.sample_width
        
        while not self.is_complete:
            chunk = self.read(chunk_size)
            if chunk:
                if len(chunk) < chunk_size:
                    chunk = chunk + b"\x00" * (chunk_size - len(chunk))
                yield chunk
                
                if interval_ms:
                    await asyncio.sleep(interval_ms / 1000)
    
    def to_numpy(self) -> np.ndarray:
        """Convert to numpy array (int16)."""
        return np.frombuffer(self._data, dtype=np.int16)
    
    def resample(self, target_rate: int) -> "AudioStream":
        """
        Resample audio to different sample rate.
        
        Simple linear interpolation - for production use
        a proper resampling library like scipy.
        
        Args:
            target_rate: Target sample rate
            
        Returns:
            Resampled AudioStream
        """
        if target_rate == self._format.sample_rate:
            return AudioStream(self._data, self._format)
        
        samples = self.to_numpy()
        ratio = target_rate / self._format.sample_rate
        
        # Simple linear interpolation
        old_len = len(samples)
        new_len = int(old_len * ratio)
        
        old_indices = np.arange(old_len)
        new_indices = np.linspace(0, old_len - 1, new_len)
        
        resampled = np.interp(new_indices, old_indices, samples).astype(np.int16)
        
        new_format = AudioFormat(
            sample_rate=target_rate,
            sample_width=self._format.sample_width,
            channels=self._format.channels,
        )
        
        return AudioStream(resampled.tobytes(), new_format)


