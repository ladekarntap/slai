# Arista 7050CX3 Monitoring Automation

## Files
- `Chiffon/nate_hosts`
- `Chiffon/monitor_arista_7050cx3.py`
- `Chiffon/run_monitoring.sh`

## Prerequisites
```bash
pip install netmiko
```

## Required environment variables
Credentials must come from environment variables (no plaintext secrets in files):

```bash
export ARISTA_USER='your-username'
export ARISTA_PASS='your-password'
export ARISTA_ENABLE_PASS='your-enable-password'   # optional
export ARISTA_HOSTS='steswitch-vino-aswt01,steswitch-vino-aswt02'   # optional
```

## Run
```bash
bash Chiffon/run_monitoring.sh
```

## Output and exit codes
- JSON report: `Chiffon/arista_monitoring_result.json`
- Exit code `0`: all checks passed
- Exit code `1`: one or more checks failed
- Exit code `2`: missing required environment variables
