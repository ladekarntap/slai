#!/usr/bin/env python3
"""
Generate a Cisco Nexus 9364D switch configuration text file.

This script produces a NetApp-style reference configuration for a Cisco
Nexus 9364D switch using cluster and storage counts as inputs.

Example:
    python cisco_nexus_generate_L2_switch_config_file.py \
        --clusters 3 --storages 3 --output RCF-v20.1-NX9364D-CL3-ST3.txt
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import List, Tuple


VERSION = "v20.1"
SWITCH_MODEL = "NX9364D"
DEFAULT_FILENAME_TEMPLATE = "RCF-{version}-{model}-CL{clusters}-ST{storages}.txt"

# Fixed starting port layout per group on a 64-port switch
CLUSTER_PORT_STARTS = [1, 11, 21]
STORAGE_200G_PORT_STARTS = [4, 14, 24]
STORAGE_100G_PORT_STARTS = [7, 17, 27]
ISL_PORTS = (63, 64)


def build_cluster_vlans(index: int) -> dict:
    base_native = 50 + (index - 1) * 10
    return {
        "native": base_native,
        "ha1": base_native + 1,
        "ha2": base_native + 2,
        "dcn": base_native + 3,
    }


def build_storage_vlans(index: int) -> dict:
    storage = 31 + (index - 1) * 2
    return {
        "storage": storage,
        "native": storage + 1,
    }


def interface_range_200g(start_port: int) -> str:
    return f"e1/{start_port}/1-2,e1/{start_port + 1}/1-2,e1/{start_port + 2}/1-2"


def interface_range_100g(start_port: int) -> str:
    return (
        f"e1/{start_port}/1-4,e1/{start_port + 1}/1-4,"
        f"e1/{start_port + 2}/1-4,e1/{start_port + 3}/1-4"
    )


def comma_join(values: List[int]) -> str:
    return ",".join(str(v) for v in values)


def build_banner(filename: str, clusters: int, storages: int, date_str: str) -> str:
    port_usage = []
    for i in range(clusters):
        cl_num = i + 1
        cl_start = CLUSTER_PORT_STARTS[i]
        port_usage.append(
            f"* Ports {cl_start:>2}-{cl_start + 2}: CL-{cl_num} 200GbE breakout Intra-Cluster/HA Ports, int e1/{{{cl_start}-{cl_start + 2}}}/1-2"
        )

        if i < storages:
            st_200 = STORAGE_200G_PORT_STARTS[i]
            st_100 = STORAGE_100G_PORT_STARTS[i]
            port_usage.append(
                f"* Ports {st_200:>2}-{st_200 + 2}: ST-{cl_num} 200GbE breakout Storage Ports, int e1/{{{st_200}-{st_200 + 2}}}/1-2"
            )
            port_usage.append(
                f"* Ports {st_100:>2}-{st_100 + 3}: ST-{cl_num} 100GbE breakout Storage Shelf Ports, int e1/{{{st_100}-{st_100 + 3}}}/1-4"
            )

    port_usage.append(
        f"* Ports {ISL_PORTS[0]}-{ISL_PORTS[1]}: Intra-Cluster ISL Ports, int e1/{ISL_PORTS[0]}-{ISL_PORTS[1]}"
    )

    return "\n".join(
        [
            "banner motd #",
            "******************************************************************************",
            "* NetApp Reference Configuration File (RCF)",
            "*",
            f"* Switch   : {SWITCH_MODEL}",
            f"* Filename : {filename}",
            f"* Date     : {date_str}",
            f"* Version  : {VERSION}",
            "* Port Usage:",
            *port_usage,
            "*",
            "* IMPORTANT NOTES:",
            "* Interfaces port-channel 998 (legacy) and 999 (latest) are reserved to",
            "* identify the version of this RCF.",
            "******************************************************************************",
            "#",
        ]
    )


def build_installation_notes() -> str:
    return """# Installation Notes:
#
# Cluster VLAN Table:
# ---------------------------------------------------
# | CL-1 | Cluster/Native: 50 | HA: 51,52 | DCN: 53 |
# | CL-2 | Cluster/Native: 60 | HA: 61,62 | DCN: 63 |
# | CL-3 | Cluster/Native: 70 | HA: 71,72 | DCN: 73 |
# ---------------------------------------------------
#
# Storage VLAN Table:
# -----------------------------------
# | ST-1 | Storage: 31 | Native: 32 |
# | ST-2 | Storage: 33 | Native: 34 |
# | ST-3 | Storage: 35 | Native: 36 |
# -----------------------------------
#
# ISL Allowed VLANs: 50,53,60,63,70,73
#
# IMPORTANT NOTES
# Under certain conditions, the switch might not be able to auto-negotiate the
# port speed correctly. Manually set the port speed in config mode, e.g.
# int e1/1/1
# speed 200000
# int e1/7/3
# speed 100000
# int e1/63
# speed 400000
#
"""


def build_breakout_config(clusters: int, storages: int) -> str:
    ports_200g: List[str] = []
    ports_100g: List[str] = []

    for i in range(clusters):
        cl_start = CLUSTER_PORT_STARTS[i]
        ports_200g.append(f"{cl_start}-{cl_start + 2}")

    for i in range(storages):
        st_200 = STORAGE_200G_PORT_STARTS[i]
        st_100 = STORAGE_100G_PORT_STARTS[i]
        ports_200g.append(f"{st_200}-{st_200 + 2}")
        ports_100g.append(f"{st_100}-{st_100 + 3}")

    sections = []
    if ports_200g:
        sections.append(f"interface breakout module 1 port {','.join(ports_200g)} map 200g-2x")
    if ports_100g:
        sections.append(f"interface breakout module 1 port {','.join(ports_100g)} map 100g-4x")
    return "\n".join(sections)


def build_base_config(vlan_values: List[int]) -> str:
    vlan_line = comma_join(vlan_values)
    return f"""
feature lacp
feature lldp
feature ssh
feature sftp-server
feature scp-server

vlan {vlan_line}
exit

cdp enable
cdp advertise v1
cdp timer 5
system default switchport
no system default switchport shutdown
no feature signature-verification
snmp-server community cshm1! group network-operator
errdisable recovery interval 30
port-channel load-balance src-dst ip-l4port-vlan
ip domain-lookup
logging console 1

hardware access-list tcam region ing-racl 1024
hardware access-list tcam region egr-racl 1024
hardware access-list tcam region ing-l2-qos 1536
hardware access-list tcam label ing-ifacl 6

#********** Keyless SSH for SHM **********
ssh key ecdsa 521
#********** PFC/QoS/ECN **********

class-map type qos match-all HA
match cos 5
exit

class-map type qos match-all STORAGE
match cos 3
exit
class-map type qos match-any RDMA
 match dscp 16
 match cos 2

policy-map type qos HA_STORAGE_POLICY
class type qos HA
  set qos-group 5


class type qos STORAGE
set qos-group 3
class type qos RDMA
  set qos-group 2
class type qos class-default
  set qos-group 0


policy-map type queuing EGRESS_POLICY
class type queuing c-out-8q-q7
bandwidth remaining percent 0
class type queuing c-out-8q-q6
bandwidth remaining percent 0
class type queuing c-out-8q-q5
bandwidth remaining percent 0
random-detect threshold burst-optimized ecn
class type queuing c-out-8q-q4
bandwidth remaining percent 0
class type queuing c-out-8q-q3
random-detect minimum-threshold 150 kbytes maximum-threshold 1500 kbytes drop-probability 100 weight 0 ecn
bandwidth remaining percent 0
class type queuing c-out-8q-q2
bandwidth remaining percent 0
random-detect threshold burst-optimized ecn
class type queuing c-out-8q-q1
bandwidth remaining percent 0
class type queuing c-out-8q-q-default
bandwidth remaining percent 0
random-detect threshold burst-optimized ecn

policy-map type network-qos NETQOS_POLICY
class type network-qos c-8q-nq5
pause pfc-cos 5
mtu 9216
class type network-qos c-8q-nq3
pause pfc-cos 3
mtu 9216
class type network-qos c-8q-nq2
mtu 9216
class type network-qos c-8q-nq-default
mtu 9216
exit
exit

system qos
service-policy type network-qos NETQOS_POLICY
service-policy type queuing output EGRESS_POLICY

copp profile strict
""".strip()


def build_cluster_profiles(clusters: int) -> str:
    parts = ["#********** Port Profiles for CL-1, CL-2, CL-3 **********", ""]
    for i in range(1, clusters + 1):
        vlans = build_cluster_vlans(i)
        parts.append(
            f"""port-profile type ethernet CL{i}_HA
description CL-{i} 200GbE Intra-Cluster/HA Nodes
switchport mode trunk
switchport vlan mapping enable
switchport trunk native vlan {vlans['native']}
switchport vlan mapping 17 {vlans['ha1']}
switchport vlan mapping 18 {vlans['ha2']}
switchport vlan mapping 40 {vlans['dcn']}
switchport trunk allowed vlan {vlans['native']},{vlans['ha1']},{vlans['ha2']},{vlans['dcn']}
spanning-tree port type edge trunk
spanning-tree bpduguard enable
spanning-tree guard root
switchport block unicast
storm-control unicast level 50
storm-control broadcast level 40
priority-flow-control mode on
priority-flow-control watch-dog-interval on
mtu 9216
state enabled
exit
"""
        )
    return "\n".join(parts).strip()


def build_storage_profiles(storages: int) -> str:
    parts = ["#********** Port Profiles for ST-1, ST-2, ST-3 **********", ""]
    for i in range(1, storages + 1):
        vlans = build_storage_vlans(i)
        parts.append(
            f"""port-profile type ethernet ST{i}
description ST-{i} Controller/Shelf Storage Port
switchport mode trunk
switchport vlan mapping enable
switchport vlan mapping 30 dot1q-tunnel {vlans['storage']}
switchport trunk native vlan {vlans['native']}
switchport trunk allowed vlan {vlans['storage']},{vlans['native']}
spanning-tree port type edge trunk
spanning-tree bpduguard enable
switchport block unicast
storm-control unicast level 50
storm-control broadcast level 40
priority-flow-control mode on
priority-flow-control watch-dog-interval on
mtu 9216
state enabled
exit
"""
        )
    return "\n".join(parts).strip()


def build_cluster_interfaces(clusters: int) -> str:
    parts = ["#********** Interfaces for CL-1, CL-2, CL-3 **********", ""]
    for i in range(clusters):
        idx = i + 1
        parts.append(
            f"""interface {interface_range_200g(CLUSTER_PORT_STARTS[i])}
description CL-{idx} Cluster/HA 200G Port
inherit port-profile CL{idx}_HA
priority-flow-control mode on
priority-flow-control watch-dog-interval on
service-policy type qos input HA_STORAGE_POLICY
exit
"""
        )
    return "\n".join(parts).strip()


def build_storage_interfaces(storages: int) -> str:
    parts = ["#********** Interfaces for ST-1, ST-2, ST-3 **********", ""]
    for i in range(storages):
        idx = i + 1
        parts.append(
            f"""interface {interface_range_200g(STORAGE_200G_PORT_STARTS[i])}
description ST-{idx} Storage 200G Port
inherit port-profile ST{idx}
priority-flow-control mode on
priority-flow-control watch-dog-interval on
service-policy type qos input HA_STORAGE_POLICY
exit
"""
        )
        parts.append(
            f"""interface {interface_range_100g(STORAGE_100G_PORT_STARTS[i])}
description ST-{idx} Storage 100G Port
inherit port-profile ST{idx}
priority-flow-control mode on
priority-flow-control watch-dog-interval on
service-policy type qos input HA_STORAGE_POLICY
exit
"""
        )
    return "\n".join(parts).strip()


def build_isl_section(allowed_vlans: List[int]) -> str:
    allowed = comma_join(allowed_vlans)
    return f"""#********** Intra-Cluster ISL ports **********
interface port-channel1
description LOCAL_ISL Switch
switchport mode trunk
priority-flow-control mode on
priority-flow-control watch-dog-interval on
switchport trunk allowed vlan {allowed}
mtu 9216
service-policy type qos input HA_STORAGE_POLICY
no shutdown

interface Ethernet1/{ISL_PORTS[0]}
description LOCAL_ISL Switch 400G Port
priority-flow-control mode on
priority-flow-control watch-dog-interval on
switchport mode trunk
switchport trunk allowed vlan {allowed}
mtu 9216
channel-group 1 mode active
no shutdown

interface Ethernet1/{ISL_PORTS[1]}
description LOCAL_ISL Switch 400G Port
priority-flow-control mode on
priority-flow-control watch-dog-interval on
switchport mode trunk
switchport trunk allowed vlan {allowed}
mtu 9216
channel-group 1 mode active
no shutdown
"""


def build_version_port_channels(clusters: int, storages: int) -> str:
    return f"""interface port-channel998
  shutdown
  description RCF {SWITCH_MODEL} {VERSION} {clusters}-CLUSTER {storages}-STORAGE AFX
exit

interface port-channel999
  shutdown
  description RCF {VERSION} {SWITCH_MODEL} CL-{clusters} ST-{storages}
end
"""


def collect_vlans(clusters: int, storages: int) -> Tuple[List[int], List[int]]:
    vlan_values: List[int] = []
    isl_allowed: List[int] = []

    for i in range(1, clusters + 1):
        v = build_cluster_vlans(i)
        vlan_values.extend([v["native"], v["ha1"], v["ha2"], v["dcn"]])
        isl_allowed.extend([v["native"], v["dcn"]])

    for i in range(1, storages + 1):
        v = build_storage_vlans(i)
        vlan_values.extend([v["storage"], v["native"]])

    return vlan_values, isl_allowed


def generate_config(clusters: int, storages: int, filename: str) -> str:
    date_str = datetime.now().strftime("%m-%d-%Y")
    all_vlans, isl_allowed = collect_vlans(clusters, storages)

    sections = [
        build_installation_notes().rstrip(),
        build_banner(filename, clusters, storages, date_str),
        build_breakout_config(clusters, storages),
        build_base_config(all_vlans),
        build_cluster_profiles(clusters),
        build_storage_profiles(storages),
        build_cluster_interfaces(clusters),
        build_storage_interfaces(storages),
        build_isl_section(isl_allowed).rstrip(),
        build_version_port_channels(clusters, storages).rstrip(),
    ]

    return "\n\n".join(section for section in sections if section.strip()) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate Cisco Nexus 9364D L2 switch configuration file"
    )
    parser.add_argument(
        "--clusters",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Number of cluster groups (1-3)",
    )
    parser.add_argument(
        "--storages",
        type=int,
        default=3,
        choices=[1, 2, 3],
        help="Number of storage groups (1-3)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Output .txt filename",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_name = args.output or DEFAULT_FILENAME_TEMPLATE.format(
        version=VERSION,
        model=SWITCH_MODEL,
        clusters=args.clusters,
        storages=args.storages,
    )

    config_text = generate_config(args.clusters, args.storages, output_name)
    output_path = Path(output_name)
    output_path.write_text(config_text, encoding="utf-8")
    print(f"Generated config file: {output_path}")


if __name__ == "__main__":
    main()
