# PySIP Load Test

Tests how many simultaneous calls PySIP can handle with metrics on:
- Maximum concurrent calls
- Call success/failure rate  
- Call setup latency
- Audio quality (packet loss, jitter)
- Resource usage (CPU, memory)

## Setup

1. Create `extensions.csv` with your SIP credentials:

```csv
username,password,server,port
1,password001,77.37.67.125,5060
2,password002,77.37.67.125,5060
3,password003,77.37.67.125,5060
4,password004,77.37.67.125,5060
```

**Note:** First half of credentials are used as receivers, second half as callers.
For N call pairs, you need 2N credentials.

2. Install optional dependency for resource monitoring:
```bash
pip install psutil
```

## Usage

```bash
# Basic test (1 call pair with 2 credentials)
python -m tests.perf.load_test --credentials tests/perf/extensions.csv --duration 30

# Longer test with more calls
python -m tests.perf.load_test --credentials tests/perf/extensions.csv --duration 60 --ramp-rate 5
```

## Options

| Option | Default | Description |
|--------|---------|-------------|
| `--credentials`, `-c` | required | Path to CSV file with SIP credentials |
| `--duration`, `-d` | 30 | How long to maintain calls (seconds) |
| `--ramp-rate`, `-r` | 5 | Calls to start per second |
| `--output`, `-o` | tests/perf/results | Output directory for results |

## Output

Results are saved to `tests/perf/results/<timestamp>/`:
- `report.txt` - Human-readable summary
- `metrics.json` - Detailed metrics for analysis
- `recordings/` - Audio recordings from receivers

## Example Output

```
PySIP Load Test Results
==================================================
Test Time: 2026-01-03T16:00:00
Test Duration: 35.2s
Target Calls: 10

Call Results:
  Peak Concurrent Calls: 10
  Successful Calls: 10/10 (100.0%)
  Failed Calls: 0

Call Setup Latency:
  Min: 45ms
  Avg: 123ms
  Max: 892ms
  P95: 450ms

Audio Quality:
  Avg Packet Loss: 0.2%
  Avg Jitter: 12.3ms
  Avg RTT: 45.2ms

Resource Usage:
  Peak CPU: 34.2%
  Peak Memory: 156MB
```
