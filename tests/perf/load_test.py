#!/usr/bin/env python3
"""
PySIP Load Test

Tests how many simultaneous calls PySIP can handle with metrics on:
- Maximum concurrent calls
- Call success/failure rate
- Call setup latency
- Audio quality (packet loss, jitter)
- Resource usage (CPU, memory)

Usage:
    python -m tests.perf.load_test --credentials extensions.csv --duration 30
    python -m tests.perf.load_test --credentials extensions.csv --duration 60 --ramp-rate 5

CSV Format:
    username,password,server,port
    1,password001,77.37.67.125,5060
    2,password002,77.37.67.125,5060
"""

import argparse
import asyncio
import csv
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Callable, Awaitable

# Add parent directory to path for development
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(Path(__file__).parent.parent.parent / '.env')

from PySIP import SIPClient
from PySIP.exceptions import (
    CallFailedError,
    CallRejectedError,
    CallTimeoutError,
    RegistrationError,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce noise from PySIP internals during load test
logging.getLogger('PySIP').setLevel(logging.WARNING)


@dataclass
class SIPCredential:
    """SIP account credentials."""
    
    username: str
    password: str
    server: str
    port: int = 5060


@dataclass
class LoadTestConfig:
    """Configuration for load test."""
    
    credentials: list[SIPCredential] = field(default_factory=list)
    duration: float = 30.0
    ramp_rate: float = 5.0  # Calls per second
    output_dir: Path = field(default_factory=lambda: Path("tests/perf/results"))
    
    @property
    def num_calls(self) -> int:
        """Number of call pairs possible (half credentials each side)."""
        return len(self.credentials) // 2
    
    @classmethod
    def from_csv(cls, csv_path: Path, duration: float = 30.0, ramp_rate: float = 5.0) -> "LoadTestConfig":
        """Load credentials from CSV file."""
        credentials = []
        
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Skip empty rows
                if not row.get('username'):
                    continue
                    
                cred = SIPCredential(
                    username=row['username'].strip(),
                    password=row['password'].strip(),
                    server=row['server'].strip(),
                    port=int(row.get('port', 5060)),
                )
                credentials.append(cred)
        
        return cls(
            credentials=credentials,
            duration=duration,
            ramp_rate=ramp_rate,
        )


@dataclass
class CallMetrics:
    """Metrics for a single call."""
    
    call_id: str = ""
    caller: str = ""
    callee: str = ""
    
    # Timing
    start_time: float = 0.0
    connect_time: float = 0.0
    end_time: float = 0.0
    setup_latency_ms: float = 0.0
    duration_seconds: float = 0.0
    
    # Status
    successful: bool = False
    error: str = ""
    
    # Audio quality (from RTP stats)
    packets_sent: int = 0
    packets_received: int = 0
    packets_lost: int = 0
    packet_loss_percent: float = 0.0
    jitter_ms: float = 0.0
    rtt_ms: float = 0.0


@dataclass
class ResourceSample:
    """Resource usage sample."""
    
    timestamp: float
    cpu_percent: float
    memory_mb: float
    active_calls: int


@dataclass 
class LoadTestResults:
    """Aggregated load test results."""
    
    # Test info
    test_start: str = ""
    test_duration: float = 0.0
    target_calls: int = 0
    
    # Call results
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    success_rate: float = 0.0
    peak_concurrent_calls: int = 0
    
    # Latency stats (ms)
    latency_min: float = 0.0
    latency_avg: float = 0.0
    latency_max: float = 0.0
    latency_p95: float = 0.0
    
    # Audio quality
    avg_packet_loss: float = 0.0
    avg_jitter: float = 0.0
    avg_rtt: float = 0.0
    
    # Resource usage
    peak_cpu: float = 0.0
    peak_memory_mb: float = 0.0
    avg_cpu: float = 0.0
    avg_memory_mb: float = 0.0
    
    # Detailed data
    call_metrics: list = field(default_factory=list)
    resource_samples: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class MetricsCollector:
    """Collects and aggregates metrics during load test."""
    
    def __init__(self):
        self.call_metrics: list[CallMetrics] = []
        self.resource_samples: list[ResourceSample] = []
        self.active_calls: int = 0
        self.peak_concurrent: int = 0
        self._lock = asyncio.Lock()
        self._resource_task: asyncio.Task | None = None
        self._running = False
    
    async def start(self):
        """Start resource monitoring."""
        self._running = True
        self._resource_task = asyncio.create_task(self._monitor_resources())
    
    async def stop(self):
        """Stop resource monitoring."""
        self._running = False
        if self._resource_task:
            self._resource_task.cancel()
            try:
                await self._resource_task
            except asyncio.CancelledError:
                pass
    
    async def _monitor_resources(self):
        """Periodically sample resource usage."""
        try:
            import psutil
            process = psutil.Process()
        except ImportError:
            logger.warning("psutil not installed - resource monitoring disabled")
            return
        
        try:
            while self._running:
                sample = ResourceSample(
                    timestamp=time.time(),
                    cpu_percent=process.cpu_percent(),
                    memory_mb=process.memory_info().rss / (1024 * 1024),
                    active_calls=self.active_calls,
                )
                self.resource_samples.append(sample)
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
    
    async def call_started(self):
        """Record a call starting."""
        async with self._lock:
            self.active_calls += 1
            if self.active_calls > self.peak_concurrent:
                self.peak_concurrent = self.active_calls
    
    async def call_ended(self, metrics: CallMetrics):
        """Record a call ending with its metrics."""
        async with self._lock:
            self.active_calls -= 1
            self.call_metrics.append(metrics)
    
    def compute_results(self, config: LoadTestConfig, test_start: float) -> LoadTestResults:
        """Compute aggregated results."""
        results = LoadTestResults(
            test_start=datetime.fromtimestamp(test_start).isoformat(),
            test_duration=time.time() - test_start,
            target_calls=config.num_calls,
            total_calls=len(self.call_metrics),
            peak_concurrent_calls=self.peak_concurrent,
        )
        
        # Call success/failure
        successful = [m for m in self.call_metrics if m.successful]
        failed = [m for m in self.call_metrics if not m.successful]
        
        results.successful_calls = len(successful)
        results.failed_calls = len(failed)
        results.success_rate = (len(successful) / len(self.call_metrics) * 100) if self.call_metrics else 0
        
        # Latency stats
        latencies = [m.setup_latency_ms for m in successful if m.setup_latency_ms > 0]
        if latencies:
            latencies.sort()
            results.latency_min = min(latencies)
            results.latency_avg = sum(latencies) / len(latencies)
            results.latency_max = max(latencies)
            # P95
            p95_idx = int(len(latencies) * 0.95)
            results.latency_p95 = latencies[min(p95_idx, len(latencies) - 1)]
        
        # Audio quality
        quality_calls = [m for m in successful if m.packets_received > 0]
        if quality_calls:
            results.avg_packet_loss = sum(m.packet_loss_percent for m in quality_calls) / len(quality_calls)
            results.avg_jitter = sum(m.jitter_ms for m in quality_calls) / len(quality_calls)
            rtt_calls = [m for m in quality_calls if m.rtt_ms > 0]
            if rtt_calls:
                results.avg_rtt = sum(m.rtt_ms for m in rtt_calls) / len(rtt_calls)
        
        # Resource usage
        if self.resource_samples:
            cpu_values = [s.cpu_percent for s in self.resource_samples]
            mem_values = [s.memory_mb for s in self.resource_samples]
            results.peak_cpu = max(cpu_values)
            results.peak_memory_mb = max(mem_values)
            results.avg_cpu = sum(cpu_values) / len(cpu_values)
            results.avg_memory_mb = sum(mem_values) / len(mem_values)
        
        # Store detailed data
        results.call_metrics = [asdict(m) for m in self.call_metrics]
        results.resource_samples = [asdict(s) for s in self.resource_samples]
        results.errors = [m.error for m in failed if m.error]
        
        return results


class LoadTestRunner:
    """Orchestrates the load test."""
    
    def __init__(self, config: LoadTestConfig):
        self.config = config
        self.metrics = MetricsCollector()
        self.receivers: list[tuple[SIPClient, SIPCredential]] = []
        self.callers: list[tuple[SIPClient, SIPCredential]] = []
        self._receiver_ready: dict[str, asyncio.Event] = {}
        
        # Split credentials: first half receivers, second half callers
        n = len(config.credentials) // 2
        self._receiver_creds = config.credentials[:n]
        self._caller_creds = config.credentials[n:2*n]
    
    async def run(self) -> LoadTestResults:
        """Run the load test."""
        test_start = time.time()
        
        # Get server info from first credential
        server_info = "N/A"
        if self.config.credentials:
            c = self.config.credentials[0]
            server_info = f"{c.server}:{c.port}"
        
        print(f"\n{'='*60}")
        print(f"PySIP Load Test")
        print(f"{'='*60}")
        print(f"Server: {server_info}")
        print(f"Credentials Loaded: {len(self.config.credentials)}")
        print(f"Target Call Pairs: {self.config.num_calls}")
        print(f"Duration: {self.config.duration}s")
        print(f"Ramp Rate: {self.config.ramp_rate} calls/sec")
        print(f"{'='*60}\n")
        
        try:
            # Start metrics collection
            await self.metrics.start()
            
            # Setup phase
            print("Phase 1: Setting up receivers...")
            await self._setup_receivers()
            
            print("Phase 2: Setting up callers...")
            await self._setup_callers()
            
            # Run calls (each call runs for duration, playing TTS)
            print(f"Phase 3: Running {self.config.num_calls} call pairs for {self.config.duration}s...")
            await self._run_calls()
            
        except Exception as e:
            logger.error(f"Load test error: {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            # Cleanup
            print("\nPhase 4: Cleaning up...")
            await self._cleanup()
            await self.metrics.stop()
        
        # Compute results
        results = self.metrics.compute_results(self.config, test_start)
        
        return results
    
    async def _setup_receivers(self):
        """Set up receiver clients that wait for calls."""
        for cred in self._receiver_creds:
            client = SIPClient(
                username=cred.username,
                password=cred.password,
                server=cred.server,
                port=cred.port,
            )
            
            try:
                await client.start()
                await client.register()
                
                # Set up call handler
                ready_event = asyncio.Event()
                self._receiver_ready[cred.username] = ready_event
                
                @client.on_incoming_call
                async def handle_call(call, user=cred.username, ready=ready_event, runner=self):
                    ready.set()
                    try:
                        await call.answer()
                        logger.info(f"Receiver {user} answered call")
                        
                        # Small delay to ensure RTP is ready
                        await asyncio.sleep(0.2)
                        
                        # Start recording in background to capture caller's audio
                        recording_task = asyncio.create_task(
                            call.record(
                                max_duration=runner.config.duration + 10,  # Extra buffer
                                silence_timeout=runner.config.duration + 5,
                            )
                        )
                        
                        # Send audio back to create two-way RTP traffic
                        message_count = 0
                        while call.is_active:
                            try:
                                message_count += 1
                                await call.say(
                                    f"Receiver response number {message_count}. "
                                    "Sending audio back to caller for two-way test. "
                                    "Measuring bidirectional audio quality."
                                )
                            except Exception as e:
                                logger.debug(f"Receiver {user} TTS error: {e}")
                                break
                        
                        # Save recording if completed
                        try:
                            recording = await asyncio.wait_for(recording_task, timeout=5.0)
                            if recording and len(recording.audio) > 0:
                                # Save to results directory
                                rec_dir = runner.config.output_dir / "recordings"
                                rec_dir.mkdir(parents=True, exist_ok=True)
                                filename = rec_dir / f"receiver_{user}_{call.call_id[:8]}.wav"
                                recording.save(str(filename))
                                logger.info(f"Receiver {user} saved recording: {filename.name} ({recording.duration_seconds:.1f}s)")
                        except asyncio.TimeoutError:
                            recording_task.cancel()
                        except Exception as e:
                            logger.debug(f"Receiver {user} recording save error: {e}")
                            
                    except Exception as e:
                        logger.debug(f"Receiver {user} call error: {e}")
                
                self.receivers.append((client, cred))
                logger.info(f"Receiver {cred.username} ready")
                
            except Exception as e:
                logger.error(f"Failed to setup receiver {cred.username}: {e}")
        
        print(f"  {len(self.receivers)} receivers ready")
    
    async def _setup_callers(self):
        """Set up caller clients."""
        for cred in self._caller_creds:
            client = SIPClient(
                username=cred.username,
                password=cred.password,
                server=cred.server,
                port=cred.port,
            )
            
            try:
                await client.start()
                await client.register()
                self.callers.append((client, cred))
                logger.info(f"Caller {cred.username} ready")
                
            except Exception as e:
                logger.error(f"Failed to setup caller {cred.username}: {e}")
        
        print(f"  {len(self.callers)} callers ready")
    
    async def _run_calls(self):
        """Start calls with ramping and wait for them to complete."""
        call_tasks = []
        
        for i in range(min(len(self.callers), len(self.receivers))):
            # Create call task
            task = asyncio.create_task(
                self._make_call(i)
            )
            call_tasks.append(task)
            
            # Ramp delay between starting calls
            if self.config.ramp_rate > 0 and i < len(self.callers) - 1:
                delay = 1.0 / self.config.ramp_rate
                await asyncio.sleep(delay)
        
        print(f"  {len(call_tasks)} calls initiated, waiting for completion...")
        
        # Wait for all calls to complete (they run for duration)
        await asyncio.gather(*call_tasks, return_exceptions=True)
        
        print(f"  All calls completed")
    
    async def _make_call(self, index: int):
        """Make a single call and collect metrics."""
        caller_client, caller_cred = self.callers[index]
        _, receiver_cred = self.receivers[index]
        
        caller_user = caller_cred.username
        callee_user = receiver_cred.username
        
        metrics = CallMetrics(
            caller=caller_user,
            callee=callee_user,
            start_time=time.time(),
        )
        
        await self.metrics.call_started()
        
        try:
            # Make call
            call = caller_client.dial(callee_user, timeout=30.0)
            
            # Connect
            connect_start = time.time()
            await call.connect()
            metrics.connect_time = time.time()
            metrics.setup_latency_ms = (metrics.connect_time - connect_start) * 1000
            metrics.call_id = call.call_id
            metrics.successful = True
            
            logger.info(f"Call {index+1} connected: {caller_user} -> {callee_user} ({metrics.setup_latency_ms:.0f}ms)")
            
            # Play TTS audio to generate RTP traffic for quality measurement
            # Keep playing messages until duration is reached
            call_start = time.time()
            message_count = 0
            
            while call.is_active and (time.time() - call_start) < self.config.duration:
                try:
                    message_count += 1
                    # Play a test message (this generates RTP packets)
                    await call.say(
                        f"This is load test message number {message_count}. "
                        "Testing PySIP performance with continuous audio streaming. "
                        "Measuring packet loss, jitter, and latency metrics."
                    )
                except Exception as e:
                    logger.debug(f"Call {index+1} TTS error: {e}")
                    break
            
            # Collect RTP stats after audio has been sent
            if call._rtp_session:
                stats = call._rtp_session.stats
                metrics.packets_sent = stats.packets_sent
                metrics.packets_received = stats.packets_received
                metrics.packets_lost = stats.packets_lost
                if stats.packets_received > 0:
                    metrics.packet_loss_percent = (stats.packets_lost / stats.packets_received) * 100
                metrics.jitter_ms = stats.jitter
                metrics.rtt_ms = stats.rtt
            
            # Hangup
            if call.is_active:
                await call.hangup()
            
            metrics.end_time = time.time()
            metrics.duration_seconds = metrics.end_time - metrics.connect_time
            
            logger.info(f"Call {index+1} ended: {metrics.packets_sent} pkts sent, {metrics.packets_received} pkts recv")
            
        except CallTimeoutError:
            metrics.successful = False
            metrics.error = "Timeout"
            logger.warning(f"Call {index+1} timeout: {caller_user} -> {callee_user}")
            
        except CallRejectedError as e:
            metrics.successful = False
            metrics.error = f"Rejected: {e.status_code}"
            logger.warning(f"Call {index+1} rejected: {caller_user} -> {callee_user} - {e}")
            
        except Exception as e:
            metrics.successful = False
            metrics.error = str(e)
            logger.error(f"Call {index+1} error: {caller_user} -> {callee_user} - {e}")
            import traceback
            traceback.print_exc()
        
        finally:
            metrics.end_time = metrics.end_time or time.time()
            await self.metrics.call_ended(metrics)
    
    async def _cleanup(self):
        """Stop all clients."""
        # Stop callers first
        for client, _ in self.callers:
            try:
                await client.stop()
            except Exception:
                pass
        
        # Then receivers
        for client, _ in self.receivers:
            try:
                await client.stop()
            except Exception:
                pass
        
        self.callers.clear()
        self.receivers.clear()
        print(f"  Cleanup complete")


def generate_report(results: LoadTestResults, output_dir: Path) -> str:
    """Generate human-readable report and save results."""
    
    # Create output directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    result_dir = output_dir / timestamp
    result_dir.mkdir(parents=True, exist_ok=True)
    
    # Generate text report
    report_lines = [
        "PySIP Load Test Results",
        "=" * 50,
        f"Test Time: {results.test_start}",
        f"Test Duration: {results.test_duration:.1f}s",
        f"Target Calls: {results.target_calls}",
        "",
        "Call Results:",
        f"  Peak Concurrent Calls: {results.peak_concurrent_calls}",
        f"  Successful Calls: {results.successful_calls}/{results.total_calls} ({results.success_rate:.1f}%)",
        f"  Failed Calls: {results.failed_calls}",
        "",
        "Call Setup Latency:",
        f"  Min: {results.latency_min:.0f}ms",
        f"  Avg: {results.latency_avg:.0f}ms",
        f"  Max: {results.latency_max:.0f}ms",
        f"  P95: {results.latency_p95:.0f}ms",
        "",
        "Audio Quality:",
        f"  Avg Packet Loss: {results.avg_packet_loss:.2f}%",
        f"  Avg Jitter: {results.avg_jitter:.1f}ms",
        f"  Avg RTT: {results.avg_rtt:.1f}ms",
        "",
        "Resource Usage:",
        f"  Peak CPU: {results.peak_cpu:.1f}%",
        f"  Avg CPU: {results.avg_cpu:.1f}%",
        f"  Peak Memory: {results.peak_memory_mb:.1f}MB",
        f"  Avg Memory: {results.avg_memory_mb:.1f}MB",
    ]
    
    if results.errors:
        report_lines.extend([
            "",
            "Errors:",
        ])
        # Count error types
        error_counts: dict[str, int] = {}
        for err in results.errors:
            error_counts[err] = error_counts.get(err, 0) + 1
        for err, count in sorted(error_counts.items(), key=lambda x: -x[1]):
            report_lines.append(f"  {err}: {count}")
    
    report = "\n".join(report_lines)
    
    # Save text report
    report_path = result_dir / "report.txt"
    report_path.write_text(report)
    
    # Save JSON metrics
    json_path = result_dir / "metrics.json"
    json_path.write_text(json.dumps(asdict(results), indent=2, default=str))
    
    print(f"\nResults saved to: {result_dir}")
    
    return report


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="PySIP Load Test - Test simultaneous call capacity",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python -m tests.perf.load_test --credentials extensions.csv --duration 30
  python -m tests.perf.load_test --credentials extensions.csv --duration 60 --ramp-rate 5
  
CSV Format (credentials file):
  username,password,server,port
  1,password001,77.37.67.125,5060
  2,password002,77.37.67.125,5060
  
Note: First half of credentials are receivers, second half are callers.
      So for 10 call pairs, you need 20 credentials in the CSV.
        """
    )
    
    parser.add_argument(
        '--credentials', '-c',
        type=Path,
        required=True,
        help='Path to CSV file with SIP credentials (username,password,server,port)'
    )
    parser.add_argument(
        '--duration', '-d',
        type=float,
        default=30.0,
        help='How long to maintain calls in seconds (default: 30)'
    )
    parser.add_argument(
        '--ramp-rate', '-r',
        type=float,
        default=5.0,
        help='Calls to start per second (default: 5)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=Path('tests/perf/results'),
        help='Output directory for results (default: tests/perf/results)'
    )
    
    return parser.parse_args()


async def main():
    """Main entry point."""
    args = parse_args()
    
    # Validate credentials file exists
    if not args.credentials.exists():
        print(f"Error: Credentials file not found: {args.credentials}")
        sys.exit(1)
    
    # Load config from CSV
    try:
        config = LoadTestConfig.from_csv(
            args.credentials,
            duration=args.duration,
            ramp_rate=args.ramp_rate,
        )
        config.output_dir = args.output
    except Exception as e:
        print(f"Error loading credentials: {e}")
        sys.exit(1)
    
    # Validate we have enough credentials
    if len(config.credentials) < 2:
        print(f"Error: Need at least 2 credentials for a call pair, got {len(config.credentials)}")
        sys.exit(1)
    
    if config.num_calls == 0:
        print(f"Error: Need at least 2 credentials for 1 call pair (got {len(config.credentials)})")
        sys.exit(1)
    
    # Run test
    runner = LoadTestRunner(config)
    results = await runner.run()
    
    # Generate report
    report = generate_report(results, config.output_dir)
    print("\n" + report)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nLoad test interrupted")
        sys.exit(1)

