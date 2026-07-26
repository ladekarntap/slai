#!/usr/bin/env python3

import os
import re
from datetime import datetime
from netmiko import ConnectHandler


NATE_FILE = "nate"
OUTPUT_DIR = "outputs"


ARISTA_COMMANDS = [
    "show version",
    "show hostname",
    "show clock",
    "show uptime",
    "show reload cause",
    "show inventory",
    "show environment all",
    "show processes top once",
    "show management api http-commands",
    "show users",
    "show logging last 200",
    "show interfaces status",
    "show interfaces description",
    "show interfaces counters rates",
    "show interfaces counters errors",
    "show interfaces transceiver",
    "show interfaces transceiver details",
    "show lldp neighbors",
    "show lldp neighbors detail",
    "show mac address-table",
    "show arp",
    "show ip interface brief",
    "show ipv6 interface brief",
    "show vrf",
    "show ip route summary",
    "show ip route",
    "show ipv6 route summary",
    "show spanning-tree",
    "show vlan",
    "show interfaces trunk",
    "show port-channel summary",
    "show lacp neighbor",
    "show running-config",
    "show startup-config",
    "show ntp status",
    "show ntp associations",
    "show ip bgp summary",
    "show bgp evpn summary",
    "show ip ospf neighbor",
    "show ip ospf interface brief",
    "show isis neighbors",
    "show mlag",
    "show mlag interfaces",
    "show mlag config-sanity",
    "show system resources",
    "show tech-support | no-more",
]


def parse_nate_file(path):
    """
    Expected supported nate file formats, for example:
      host=10.0.0.1
      username=admin
      password=secret

    or:
      hostname: 10.0.0.1
      login: admin
      password: secret
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"Credentials file not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        content = f.read()

    data = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        match = re.match(r"^\s*([A-Za-z0-9_\-]+)\s*[:=]\s*(.+?)\s*$", line)
        if match:
            key = match.group(1).strip().lower()
            value = match.group(2).strip()
            data[key] = value

    host = data.get("host") or data.get("hostname") or data.get("ip")
    username = data.get("username") or data.get("user") or data.get("login")
    password = data.get("password") or data.get("pass")

    if not host or not username or not password:
        raise ValueError(
            "nate file must contain host/hostname/ip, username/login/user, and password/pass"
        )

    return {
        "host": host,
        "username": username,
        "password": password,
    }


def collect_from_arista(device_info, commands):
    connection = ConnectHandler(
        device_type="arista_eos",
        host=device_info["host"],
        username=device_info["username"],
        password=device_info["password"],
        fast_cli=False,
    )

    results = {}
    try:
        connection.enable()
    except Exception:
        pass

    for cmd in commands:
        try:
            output = connection.send_command(
                cmd,
                expect_string=r"#",
                read_timeout=120,
                strip_prompt=False,
                strip_command=False,
            )
            results[cmd] = output
        except Exception as exc:
            results[cmd] = f"ERROR: {exc}"

    connection.disconnect()
    return results


def save_results(host, results):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    outfile = os.path.join(OUTPUT_DIR, f"{host}_eos_collection_{timestamp}.txt")

    with open(outfile, "w", encoding="utf-8") as f:
        f.write("Arista EOS Collection\n")
        f.write(f"Host: {host}\n")
        f.write(f"Timestamp: {timestamp}\n")
        f.write("=" * 80 + "\n\n")

        for command, output in results.items():
            f.write(f"$ {command}\n")
            f.write("-" * 80 + "\n")
            f.write(output)
            f.write("\n\n")

    return outfile


def main():
    creds = parse_nate_file(NATE_FILE)
    results = collect_from_arista(creds, ARISTA_COMMANDS)
    outfile = save_results(creds["host"], results)
    print(f"Collection complete. Output saved to: {outfile}")


if __name__ == "__main__":
    main()
