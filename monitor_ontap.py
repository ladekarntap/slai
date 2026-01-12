#monitor_ontap.py
*** Begin Patch
*** Add File: monitor_ontap.py
+#!/usr/bin/env python3
+"""
+ONTAP Cluster Monitor
+
+Polls NetApp ONTAP REST API endpoints and reports cluster/node/HA/network
+and storage issues. Produces console output, writes an optional log file, and
+can send an email when alerts are found.
+
+Usage: python3 monitor_ontap.py -c config.yaml
+"""
+from __future__ import annotations
+import argparse
+import logging
+import sys
+import time
+import yaml
+import requests
+from requests.auth import HTTPBasicAuth
+import smtplib
+from email.message import EmailMessage
+from typing import Dict, List
+
+
+LOG = logging.getLogger("ontap_monitor")
+
+
+class OntapMonitor:
+    def __init__(self, config: Dict):
+        self.config = config
+        self.session = requests.Session()
+        self.session.verify = config.get("verify_ssl", True)
+        self.timeout = config.get("timeout", 10)
+
+    def _request(self, base: str, path: str):
+        url = base.rstrip("/") + path
+        auth = None
+        if self.config.get("username") and self.config.get("password"):
+            auth = HTTPBasicAuth(self.config["username"], self.config["password"])
+        try:
+            r = self.session.get(url, auth=auth, timeout=self.timeout)
+            r.raise_for_status()
+            return r.json()
+        except requests.RequestException as e:
+            LOG.exception("Request failed: %s %s", url, e)
+            return None
+
+    def _check_nodes(self, base: str, alerts: List[str], cluster_res: Dict):
+        nodes = self._request(base, "/api/storage/nodes")
+        if nodes and "records" in nodes:
+            for n in nodes["records"]:
+                node_name = n.get("name")
+                node_state = n.get("state") or n.get("home_node") or "unknown"
+                cluster_res["nodes"].append({"name": node_name, "state": node_state})
+                if node_state not in ("online", "in-cluster", "healthy"):
+                    alerts.append(f"Node {node_name} state={node_state}")
+        else:
+            alerts.append("Failed to query nodes or no nodes returned")
+
+    def _check_ha(self, base: str, alerts: List[str], cluster_res: Dict):
+        ha = self._request(base, "/api/system/ha/peers")
+        if ha and "records" in ha:
+            for p in ha["records"]:
+                peer = p.get("peer") or p.get("name")
+                status = p.get("cluster_connection_state") or p.get("state") or "unknown"
+                cluster_res.setdefault("ha", []).append({"peer": peer, "status": status})
+                if status != "connected":
+                    alerts.append(f"HA peer {peer} status={status}")
+
+    def _check_interfaces(self, base: str, alerts: List[str], cluster_res: Dict):
+        ports = self._request(base, "/api/network/ip/interfaces")
+        if ports and "records" in ports:
+            for iface in ports["records"]:
+                name = iface.get("name")
+                admin = iface.get("administrative_state")
+                oper = iface.get("operational_state")
+                cluster_res.setdefault("interfaces", []).append({"name": name, "admin": admin, "oper": oper})
+                if admin != "up" or oper != "up":
+                    alerts.append(f"Interface {name} admin={admin} oper={oper}")
+        else:
+            alerts.append("Failed to query network interfaces or no interfaces returned")
+
+    def _check_physical_ports(self, base: str, alerts: List[str], cluster_res: Dict):
+        ports_phy = self._request(base, "/api/network/ports")
+        if ports_phy and "records" in ports_phy:
+            for p in ports_phy["records"]:
+                name = p.get("name")
+                status = p.get("link_state") or p.get("operational_state")
+                cluster_res.setdefault("ports", []).append({"name": name, "status": status})
+                if status and status != "up":
+                    alerts.append(f"Physical port {name} status={status}")
+
+    def _check_storage(self, base: str, alerts: List[str], cluster_res: Dict):
+        aggs = self._request(base, "/api/storage/aggregates")
+        if aggs and "records" in aggs:
+            for a in aggs["records"]:
+                name = a.get("name")
+                state = a.get("state") or a.get("status")
+                cluster_res.setdefault("aggregates", []).append({"name": name, "state": state})
+                if state and state.lower() not in ("online", "healthy"):
+                    alerts.append(f"Aggregate {name} state={state}")
+
+        vols = self._request(base, "/api/storage/volumes")
+        if vols and "records" in vols:
+            for v in vols["records"]:
+                name = v.get("name")
+                state = v.get("state") or v.get("status")
+                cluster_res.setdefault("volumes", []).append({"name": name, "state": state})
+                if state and state.lower() not in ("online", "mounted", "available"):
+                    alerts.append(f"Volume {name} state={state}")
+
+    def monitor(self) -> List[Dict]:
+        results = []
+        for cluster in self.config.get("clusters", []):
+            base = cluster.get("endpoint")
+            if not base:
+                LOG.warning("Cluster config missing endpoint: %s", cluster)
+                continue
+            LOG.info("Checking cluster %s", base)
+            cluster_res: Dict = {"endpoint": base, "nodes": [], "alerts": []}
+            alerts = cluster_res["alerts"]
+
+            # Run checks
+            self._check_nodes(base, alerts, cluster_res)
+            self._check_ha(base, alerts, cluster_res)
+            self._check_interfaces(base, alerts, cluster_res)
+            self._check_physical_ports(base, alerts, cluster_res)
+            self._check_storage(base, alerts, cluster_res)
+
+            results.append(cluster_res)
+
+        return results
+
+    def send_email(self, subject: str, body: str) -> bool:
+        smtp = self.config.get("smtp")
+        if not smtp:
+            LOG.debug("SMTP not configured, skipping email")
+            return False
+        msg = EmailMessage()
+        msg["Subject"] = subject
+        msg["From"] = smtp.get("from")
+        msg["To"] = ", ".join(smtp.get("to", []))
+        msg.set_content(body)
+
+        try:
+            host = smtp.get("host")
+            port = smtp.get("port", 25)
+            use_tls = smtp.get("use_tls", False)
+            use_ssl = smtp.get("use_ssl", False)
+            user = smtp.get("username")
+            pwd = smtp.get("password")
+            if use_ssl:
+                server = smtplib.SMTP_SSL(host, port, timeout=10)
+            else:
+                server = smtplib.SMTP(host, port, timeout=10)
+            server.ehlo()
+            if use_tls and not use_ssl:
+                server.starttls()
+                server.ehlo()
+            if user and pwd:
+                server.login(user, pwd)
+            server.send_message(msg)
+            server.quit()
+            LOG.info("Alert email sent to %s", msg["To"])
+            return True
+        except Exception:
+            LOG.exception("Failed to send alert email")
+            return False
+
+
+def load_config(path: str) -> Dict:
+    with open(path, "r") as fh:
+        return yaml.safe_load(fh)
+
+
+def setup_logging(cfg: Dict):
+    level = logging.INFO
+    fmt = "%(asctime)s %(levelname)s %(message)s"
+    log_file = cfg.get("log_file")
+    if log_file:
+        logging.basicConfig(level=level, format=fmt, filename=log_file)
+    else:
+        logging.basicConfig(level=level, format=fmt)
+
+
+def main(argv=None):
+    parser = argparse.ArgumentParser(description="ONTAP cluster monitor")
+    parser.add_argument("-c", "--config", default="config.yaml", help="Path to YAML config")
+    args = parser.parse_args(argv)
+
+    cfg = load_config(args.config)
+    setup_logging(cfg)
+    monitor = OntapMonitor(cfg)
+    res = monitor.monitor()
+
+    any_alerts = False
+    output_lines: List[str] = []
+    for cluster in res:
+        output_lines.append(f"Cluster: {cluster['endpoint']}")
+        if cluster["alerts"]:
+            any_alerts = True
+            for a in cluster["alerts"]:
+                output_lines.append(f"  ALERT: {a}")
+        else:
+            output_lines.append("  OK: no alerts")
+
+    # Print summary
+    print("\n".join(output_lines))
+    LOG.info("Monitoring run complete. alerts=%s", any_alerts)
+
+    # Email if configured and alerts present
+    if any_alerts and cfg.get("smtp"):
+        subject = cfg.get("email_subject", "ONTAP Monitor Alerts")
+        body = "\n".join(output_lines)
+        monitor.send_email(subject, body)
+
+    sys.exit(2 if any_alerts else 0)
+
+
+if __name__ == "__main__":
+    main()
+
*** End Patch
