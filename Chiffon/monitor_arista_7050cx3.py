#!/usr/bin/env python3
import json
import os
import re
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List

from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoAuthenticationException, NetmikoTimeoutException

COMMANDS = {
    "version": "show version",
    "inventory": "show inventory",
    "interfaces_status": "show interfaces status",
    "interfaces_counters_errors": "show interfaces counters errors",
    "cpu": "show processes top once",
    "memory": "show processes memory",
    "temperature": "show system environment temperature",
    "power": "show system environment power",
    "cooling": "show system environment cooling",
    "transceivers": "show interfaces transceiver",
    "mlag": "show mlag",
    "lacp_neighbor": "show lacp neighbor",
    "bgp_summary": "show ip bgp summary",
    "route_summary": "show ip route summary",
    "logging_last": "show logging last 100",
    "reload_cause": "show reload cause",
}

INTERFACE_ISSUE_RE = re.compile(r"\b(err-?disabled?|notconnect|xcvrAbsent|sfpAbsent|admin\s+down|line\s+protocol\s+down)\b", re.IGNORECASE)
ENV_ISSUE_RE = re.compile(r"\b(critical|failed|fault|overtemp|shutdown|absent)\b", re.IGNORECASE)
PERCENT_RE = re.compile(r"(\d{1,3})%")


def parse_interfaces(status_output: str, counters_output: str) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []

    for line in status_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("port", "----")):
            continue
        if INTERFACE_ISSUE_RE.search(stripped):
            issues.append({"source": "show interfaces status", "line": stripped})

    for line in counters_output.splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith(("port", "----")):
            continue
        if re.search(r"\b([1-9]\d*)\b", stripped):
            issues.append({"source": "show interfaces counters errors", "line": stripped})

    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


def parse_environment(temperature: str, power: str, cooling: str) -> Dict[str, Any]:
    issues: List[Dict[str, str]] = []
    for source, output in (("temperature", temperature), ("power", power), ("cooling", cooling)):
        for line in output.splitlines():
            stripped = line.strip()
            if stripped and ENV_ISSUE_RE.search(stripped):
                issues.append({"source": source, "line": stripped})

    return {"ok": len(issues) == 0, "issue_count": len(issues), "issues": issues}


def _collect_high_percent_lines(output: str, threshold: int) -> List[str]:
    alerts: List[str] = []
    for line in output.splitlines():
        values = [int(match.group(1)) for match in PERCENT_RE.finditer(line)]
        if values and max(values) >= threshold:
            alerts.append(line.strip())
    return alerts


def parse_performance(cpu_output: str, memory_output: str) -> Dict[str, Any]:
    cpu_alerts = _collect_high_percent_lines(cpu_output, threshold=90)
    memory_alerts = _collect_high_percent_lines(memory_output, threshold=90)
    return {
        "ok": not cpu_alerts and not memory_alerts,
        "cpu_alert_count": len(cpu_alerts),
        "memory_alert_count": len(memory_alerts),
        "cpu_alerts": cpu_alerts,
        "memory_alerts": memory_alerts,
    }


def run_checks(host: str, username: str, password: str, enable_password: str) -> Dict[str, Any]:
    host_result: Dict[str, Any] = {
        "host": host,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "ok": True,
        "errors": [],
        "checks": {},
    }

    device = {
        "device_type": "arista_eos",
        "host": host,
        "username": username,
        "password": password,
        "secret": enable_password,
        "conn_timeout": 20,
        "banner_timeout": 20,
        "fast_cli": False,
    }

    command_outputs: Dict[str, str] = {}

    try:
        connection = ConnectHandler(**device)
        if enable_password:
            connection.enable()

        for key, command in COMMANDS.items():
            command_outputs[key] = connection.send_command(command, read_timeout=90)

        connection.disconnect()

        interfaces_check = parse_interfaces(
            command_outputs["interfaces_status"], command_outputs["interfaces_counters_errors"]
        )
        environment_check = parse_environment(
            command_outputs["temperature"], command_outputs["power"], command_outputs["cooling"]
        )
        performance_check = parse_performance(command_outputs["cpu"], command_outputs["memory"])

        host_result["checks"] = {
            "interfaces": interfaces_check,
            "environment": environment_check,
            "performance": performance_check,
            "commands": {"ok": True, "commands_run": list(COMMANDS.values())},
        }

        if not interfaces_check["ok"]:
            host_result["ok"] = False
            host_result["errors"].append("Interface status/error counters indicate problems")
        if not environment_check["ok"]:
            host_result["ok"] = False
            host_result["errors"].append("Environment checks indicate problems")
        if not performance_check["ok"]:
            host_result["ok"] = False
            host_result["errors"].append("CPU or memory thresholds exceeded")

    except (NetmikoTimeoutException, NetmikoAuthenticationException) as exc:
        host_result["ok"] = False
        host_result["errors"].append(f"Connection/authentication error: {exc}")
    except Exception as exc:  # broad catch to keep per-host reporting resilient
        host_result["ok"] = False
        host_result["errors"].append(f"Unexpected error: {exc}")

    return host_result


def main() -> int:
    hosts_raw = os.getenv("ARISTA_HOSTS", "steswitch-vino-aswt01,steswitch-vino-aswt02").strip()
    username = os.getenv("ARISTA_USER", "").strip()
    password = os.getenv("ARISTA_PASS", "").strip()
    enable_password = os.getenv("ARISTA_ENABLE_PASS", "").strip()

    if not username or not password:
        print("Missing required env vars: ARISTA_USER and ARISTA_PASS", file=sys.stderr)
        return 2

    hosts = [host.strip() for host in hosts_raw.split(",") if host.strip()]
    if not hosts:
        print("No hosts found in ARISTA_HOSTS", file=sys.stderr)
        return 2

    results = [run_checks(host, username, password, enable_password) for host in hosts]
    overall_ok = all(result.get("ok", False) for result in results)

    print(json.dumps({"overall_ok": overall_ok, "results": results}, indent=2))
    return 0 if overall_ok else 1


if __name__ == "__main__":
    sys.exit(main())
