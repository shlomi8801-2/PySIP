"""
Audio Player

Non-blocking audio playback for RTP streaming.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Callable

from .stream import AudioStream, TELEPHONY_FORMAT

if TYPE_CHECKING:
    from ..media.codecs import Codec
    from ..transport.rtp import RTPSession

logger = logging.getLogger(__name__)


class PlaybackState(Enum):
    """Audio playback states."""
    IDLE = auto()
    PLAYING = auto()
    PAUSED = auto()
    STOPPED = auto()
    COMPLETED = auto()


@dataclass(slots=True)
class PlaybackHandle:
    """
    Handle for controlling playback.
    
    Example:
        handle = await call.play(audio)
        
        # Wait for completion
        await handle.wait()
        
        # Or stop early
        handle.stop()
    """
    
    player: "AudioPlayer"
    playback_id: str
    _completed_event: asyncio.Event = field(default_factory=asyncio.Event)
    
    @property
    def state(self) -> PlaybackState:
        """Current playback state."""
        return self.player.state
    
    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self.state == PlaybackState.PLAYING
    
    @property
    def is_complete(self) -> bool:
        """Check if playback completed."""
        return self.state in (PlaybackState.COMPLETED, PlaybackState.STOPPED)
    
    def pause(self) -> None:
        """Pause playback."""
        self.player.pause()
    
    def resume(self) -> None:
        """Resume playback."""
        self.player.resume()
    
    def stop(self) -> None:
        """Stop playback."""
        self.player.stop()
    
    async def wait(self, timeout: float | None = None) -> bool:
        """
        Wait for playback to complete.
        
        Args:
            timeout: Maximum wait time in seconds
            
        Returns:
            True if completed, False if timed out
        """
        try:
            if timeout:
                await asyncio.wait_for(
                    self._completed_event.wait(),
                    timeout=timeout,
                )
            else:
                await self._completed_event.wait()
            return True
        except asyncio.TimeoutError:
            return False
    
    def _mark_complete(self) -> None:
        """Mark playback as complete."""
        self._completed_event.set()


class AudioPlayer:
    """
    Non-blocking audio player for RTP streaming.
    
    Handles:
    - Timed packet sending
    - Codec encoding
    - Playback control (pause, stop)
    - Completion callbacks
    
    Example:
        player = AudioPlayer(rtp_session, codec)
        
        # Start playback
        handle = await player.play(audio_stream)
        
        # Wait for completion
        await handle.wait()
    """
    
    __slots__ = (
        "_rtp_session",
        "_codec",
        "_state",
        "_task",
        "_current_stream",
        "_current_handle",
        "_ptime_ms",
        "_samples_per_packet",
        "_on_complete",
        "_playback_counter",
    )
    
    def __init__(
        self,
        rtp_session: "RTPSession",
        codec: "Codec",
        ptime_ms: int = 20,
    ):
        """
        Initialize audio player.
        
        Args:
            rtp_session: RTP session for sending packets
            codec: Audio codec for encoding
            ptime_ms: Packet time in milliseconds
        """
        self._rtp_session = rtp_session
        self._codec = codec
        self._ptime_ms = ptime_ms
        self._samples_per_packet = (codec.clock_rate * ptime_ms) // 1000
        
        self._state = PlaybackState.IDLE
        self._task: asyncio.Task | None = None
        self._current_stream: AudioStream | None = None
        self._current_handle: PlaybackHandle | None = None
        self._on_complete: Callable[[], None] | None = None
        self._playback_counter = 0
    
    @property
    def state(self) -> PlaybackState:
        """Current playback state."""
        return self._state
    
    @property
    def is_playing(self) -> bool:
        """Check if currently playing."""
        return self._state == PlaybackState.PLAYING
    
    def on_complete(self, callback: Callable[[], None]) -> None:
        """Set completion callback."""
        self._on_complete = callback
    
    async def play(self, stream: AudioStream) -> PlaybackHandle:
        """
        Start playing audio stream.
        
        Args:
            stream: Audio stream to play
            
        Returns:
            Playback handle for control
        """
        # Stop any current playback
        await self.stop_async()
        
        # Create new handle
        self._playback_counter += 1
        handle = PlaybackHandle(
            player=self,
            playback_id=f"playback_{self._playback_counter}",
        )
        
        self._current_stream = stream
        self._current_handle = handle
        self._state = PlaybackState.PLAYING
        
        # Start playback task
        self._task = asyncio.create_task(self._playback_loop())
        
        return handle
    
    async def _playback_loop(self) -> None:
        """Main playback loop."""
        stream = self._current_stream
        if not stream:
            return
        
        bytes_per_packet = self._samples_per_packet * stream.format.sample_width
        interval = self._ptime_ms / 1000  # Convert to seconds
        
        next_send_time = asyncio.get_event_loop().time()
        first_packet = True
        
        try:
            while not stream.is_complete and self._state == PlaybackState.PLAYING:
                # Handle pause
                while self._state == PlaybackState.PAUSED:
                    await asyncio.sleep(0.01)
                    if self._state == PlaybackState.STOPPED:
                        return
                
                # Read chunk
                chunk = stream.read(bytes_per_packet)
                if not chunk:
                    break
                
                # Pad if needed
                if len(chunk) < bytes_per_packet:
                    chunk = chunk + b"\x00" * (bytes_per_packet - len(chunk))
                
                # Encode
                import numpy as np
                samples = np.frombuffer(chunk, dtype=np.int16)
                encoded = self._codec.encode(samples)
                
                # Wait for send time
                now = asyncio.get_event_loop().time()
                if next_send_time > now:
                    await asyncio.sleep(next_send_time - now)
                
                # Send RTP packet
                self._rtp_session.send(encoded, marker=first_packet)
                first_packet = False
                
                # Schedule next
                next_send_time += interval
        
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Playback error: {e}")
        
        finally:
            self._state = PlaybackState.COMPLETED
            
            # Notify completion
            if self._current_handle:
                self._current_handle._mark_complete()
            
            if self._on_complete:
                self._on_complete()
    
    def pause(self) -> None:
        """Pause playback."""
        if self._state == PlaybackState.PLAYING:
            self._state = PlaybackState.PAUSED
    
    def resume(self) -> None:
        """Resume playback."""
        if self._state == PlaybackState.PAUSED:
            self._state = PlaybackState.PLAYING
    
    def stop(self) -> None:
        """Stop playback (sync)."""
        self._state = PlaybackState.STOPPED
        if self._task and not self._task.done():
            self._task.cancel()
    
    async def stop_async(self) -> None:
        """Stop playback and wait for cleanup."""
        self.stop()
        if self._task:
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None


