#!/usr/bin/env python3
"""
Volume Migration Test Cases
Tests bidirectional volume migration:
  - Source: node1/vol1  -> Destination: node2/vol2
  - Source: node2/vol2  -> Destination: node1/vol1 (vice versa)
"""

import unittest
import subprocess
import time
import logging
import sys
import argparse

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Default configuration – override via CLI args or environment
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "node1": {
        "host": "node1",
        "vol":  "vol1",
        "user": "admin",
        "vserver": "svm1",
    },
    "node2": {
        "host": "node2",
        "vol":  "vol2",
        "user": "admin",
        "vserver": "svm2",
    },
    "ontap_cli": "ssh",          # CLI tool to reach ONTAP (ssh / rsh / mock)
    "poll_interval": 10,         # seconds between status polls
    "poll_timeout":  600,        # seconds before migration poll gives up
}


# ---------------------------------------------------------------------------
# Helper: run a shell command and return (rc, stdout, stderr)
# ---------------------------------------------------------------------------
def run_cmd(cmd: str, timeout: int = 120):
    log.debug("CMD: %s", cmd)
    result = subprocess.run(
        cmd, shell=True, capture_output=True, text=True, timeout=timeout
    )
    log.debug("RC=%d STDOUT=%s STDERR=%s", result.returncode, result.stdout.strip(), result.stderr.strip())
    return result.returncode, result.stdout.strip(), result.stderr.strip()


# ---------------------------------------------------------------------------
# VolumeMigrationManager – thin wrapper around ONTAP volume move commands
# ---------------------------------------------------------------------------
class VolumeMigrationManager:
    """Wraps ONTAP 'volume move' CLI commands executed over SSH."""

    def __init__(self, cfg: dict):
        self.cfg = cfg

    def _ssh(self, node_key: str, command: str) -> tuple:
        node = self.cfg[node_key]
        ssh_cmd = (
            f"{self.cfg['ontap_cli']} {node['user']}@{node['host']} "
            f"\"cluster exec -node {node['host']} {command}\""
        )
        return run_cmd(ssh_cmd)

    # -- volume move start ---------------------------------------------------
    def start_migration(self, src_key: str, dst_key: str) -> bool:
        """Initiate a volume move from src node/vol to dst node."""
        src = self.cfg[src_key]
        dst = self.cfg[dst_key]
        cmd = (
            f"volume move start "
            f"-vserver {src['vserver']} "
            f"-volume {src['vol']} "
            f"-destination-aggregate aggr_{dst['host']}_01 "
            f"-destination-vserver {dst['vserver']} "
            f"-cutover-window 30"
        )
        log.info(
            "Starting migration: [%s]%s/%s -> [%s]%s/%s",
            src_key, src["host"], src["vol"],
            dst_key, dst["host"], dst["vol"],
        )
        rc, out, err = self._ssh(src_key, cmd)
        if rc != 0:
            log.error("Migration start failed: %s %s", out, err)
            return False
        log.info("Migration started successfully.")
        return True

    # -- volume move show ----------------------------------------------------
    def get_migration_status(self, src_key: str) -> dict:
        """Return a dict with keys: state, percent_complete, phase."""
        src = self.cfg[src_key]
        cmd = (
            f"volume move show "
            f"-vserver {src['vserver']} "
            f"-volume {src['vol']} "
            f"-fields state,percent-complete,phase"
        )
        rc, out, err = self._ssh(src_key, cmd)
        if rc != 0:
            return {"state": "error", "percent_complete": 0, "phase": "unknown"}

        status = {"state": "unknown", "percent_complete": 0, "phase": "unknown"}
        for line in out.splitlines():
            low = line.lower()
            if "state" in low:
                status["state"] = line.split()[-1]
            if "percent" in low:
                try:
                    status["percent_complete"] = int(line.split()[-1].replace("%", ""))
                except ValueError:
                    pass
            if "phase" in low:
                status["phase"] = line.split()[-1]
        return status

    # -- poll until done -----------------------------------------------------
    def wait_for_completion(self, src_key: str) -> bool:
        """Poll migration status until done or timeout."""
        deadline = time.time() + self.cfg["poll_timeout"]
        while time.time() < deadline:
            status = self.get_migration_status(src_key)
            log.info(
                "Migration status [%s]: state=%s phase=%s complete=%s%%",
                src_key, status["state"], status["phase"], status["percent_complete"],
            )
            if status["state"] in ("successful", "success", "completed"):
                log.info("Migration completed successfully.")
                return True
            if status["state"] in ("failed", "error", "aborted"):
                log.error("Migration failed with state: %s", status["state"])
                return False
            time.sleep(self.cfg["poll_interval"])

        log.error("Migration timed out after %d seconds.", self.cfg["poll_timeout"])
        return False

    # -- abort ---------------------------------------------------------------
    def abort_migration(self, src_key: str) -> bool:
        src = self.cfg[src_key]
        cmd = (
            f"volume move abort "
            f"-vserver {src['vserver']} "
            f"-volume {src['vol']}"
        )
        rc, out, err = self._ssh(src_key, cmd)
        if rc != 0:
            log.error("Abort failed: %s %s", out, err)
            return False
        log.info("Migration aborted.")
        return True

    # -- verify volume location ----------------------------------------------
    def verify_volume_location(self, node_key: str, vol_key: str = None) -> bool:
        """Verify that the volume is now owned by the expected node."""
        node = self.cfg[node_key]
        volume = vol_key if vol_key else node["vol"]
        cmd = (
            f"volume show -vserver {node['vserver']} "
            f"-volume {volume} -fields node"
        )
        rc, out, err = self._ssh(node_key, cmd)
        if rc != 0:
            log.error("Volume verify failed: %s %s", out, err)
            return False
        if node["host"] in out:
            log.info("Volume '%s' confirmed on node '%s'.", volume, node["host"])
            return True
        log.error(
            "Volume '%s' NOT found on expected node '%s'. Output: %s",
            volume, node["host"], out,
        )
        return False


# ---------------------------------------------------------------------------
# Test Cases
# ---------------------------------------------------------------------------
class TestVolumeMigration(unittest.TestCase):
    """
    Bidirectional volume migration test suite.

    Forward  : node1/vol1 -> node2/vol2
    Vice-Versa: node2/vol2 -> node1/vol1
    """

    @classmethod
    def setUpClass(cls):
        cls.cfg = DEFAULT_CONFIG
        cls.mgr = VolumeMigrationManager(cls.cfg)

    # -----------------------------------------------------------------------
    # TC-01 : Forward migration  node1/vol1 -> node2
    # -----------------------------------------------------------------------
    def test_01_forward_migration_start(self):
        """TC-01: Start volume migration from node1/vol1 to node2."""
        log.info("=== TC-01: Forward migration start ===")
        result = self.mgr.start_migration(src_key="node1", dst_key="node2")
        self.assertTrue(result, "Failed to start forward migration (node1->node2)")

    def test_02_forward_migration_completion(self):
        """TC-02: Wait for forward migration (node1/vol1 -> node2) to complete."""
        log.info("=== TC-02: Forward migration completion ===")
        success = self.mgr.wait_for_completion(src_key="node1")
        self.assertTrue(success, "Forward migration did not complete successfully")

    def test_03_forward_migration_verify(self):
        """TC-03: Verify vol1 is now on node2 after forward migration."""
        log.info("=== TC-03: Verify volume location on node2 ===")
        result = self.mgr.verify_volume_location(node_key="node2", vol_key="vol1")
        self.assertTrue(result, "Volume not found on node2 after forward migration")

    # -----------------------------------------------------------------------
    # TC-04 : Reverse (vice-versa) migration  node2/vol2 -> node1
    # -----------------------------------------------------------------------
    def test_04_reverse_migration_start(self):
        """TC-04: Start volume migration from node2/vol2 back to node1 (vice versa)."""
        log.info("=== TC-04: Reverse migration start ===")
        result = self.mgr.start_migration(src_key="node2", dst_key="node1")
        self.assertTrue(result, "Failed to start reverse migration (node2->node1)")

    def test_05_reverse_migration_completion(self):
        """TC-05: Wait for reverse migration (node2/vol2 -> node1) to complete."""
        log.info("=== TC-05: Reverse migration completion ===")
        success = self.mgr.wait_for_completion(src_key="node2")
        self.assertTrue(success, "Reverse migration did not complete successfully")

    def test_06_reverse_migration_verify(self):
        """TC-06: Verify vol2 is now on node1 after reverse migration."""
        log.info("=== TC-06: Verify volume location on node1 ===")
        result = self.mgr.verify_volume_location(node_key="node1", vol_key="vol2")
        self.assertTrue(result, "Volume not found on node1 after reverse migration")

    # -----------------------------------------------------------------------
    # TC-07 : Status check before migration (negative / boundary)
    # -----------------------------------------------------------------------
    def test_07_status_when_idle(self):
        """TC-07: Migration status should return 'no active move' or similar when idle."""
        log.info("=== TC-07: Status check when no migration running ===")
        status = self.mgr.get_migration_status(src_key="node1")
        # When no migration is running the state should not be 'failed'
        self.assertNotEqual(
            status["state"], "failed",
            "Unexpected 'failed' state when no migration is running"
        )

    # -----------------------------------------------------------------------
    # TC-08 : Abort an in-progress migration (optional / manual trigger)
    # -----------------------------------------------------------------------
    def test_08_abort_migration(self):
        """
        TC-08: Start a migration and then abort it.
        NOTE: This test deliberately aborts the migration to verify abort works.
        """
        log.info("=== TC-08: Start then abort migration ===")
        started = self.mgr.start_migration(src_key="node1", dst_key="node2")
        if not started:
            self.skipTest("Could not start migration for abort test (maybe none needed)")

        time.sleep(5)  # let migration begin

        aborted = self.mgr.abort_migration(src_key="node1")
        self.assertTrue(aborted, "Abort of in-progress migration failed")

    # -----------------------------------------------------------------------
    # TC-09 : Full round-trip (forward + reverse in one test)
    # -----------------------------------------------------------------------
    def test_09_full_round_trip(self):
        """TC-09: Full round-trip: node1->node2 then node2->node1."""
        log.info("=== TC-09: Full round-trip migration ===")

        # Forward leg
        self.assertTrue(
            self.mgr.start_migration("node1", "node2"),
            "Round-trip forward start failed"
        )
        self.assertTrue(
            self.mgr.wait_for_completion("node1"),
            "Round-trip forward completion failed"
        )
        self.assertTrue(
            self.mgr.verify_volume_location("node2", "vol1"),
            "Round-trip forward verify failed"
        )

        # Reverse leg
        self.assertTrue(
            self.mgr.start_migration("node2", "node1"),
            "Round-trip reverse start failed"
        )
        self.assertTrue(
            self.mgr.wait_for_completion("node2"),
            "Round-trip reverse completion failed"
        )
        self.assertTrue(
            self.mgr.verify_volume_location("node1", "vol2"),
            "Round-trip reverse verify failed"
        )
        log.info("=== TC-09: Full round-trip PASSED ===")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------
def parse_args():
    parser = argparse.ArgumentParser(
        description="Volume migration test: node1/vol1 <-> node2/vol2"
    )
    parser.add_argument("--node1-host",    default="node1",  help="Node1 hostname")
    parser.add_argument("--node1-vol",     default="vol1",   help="Node1 volume name")
    parser.add_argument("--node1-vserver", default="svm1",   help="Node1 vserver name")
    parser.add_argument("--node1-user",    default="admin",  help="Node1 SSH user")
    parser.add_argument("--node2-host",    default="node2",  help="Node2 hostname")
    parser.add_argument("--node2-vol",     default="vol2",   help="Node2 volume name")
    parser.add_argument("--node2-vserver", default="svm2",   help="Node2 vserver name")
    parser.add_argument("--node2-user",    default="admin",  help="Node2 SSH user")
    parser.add_argument("--poll-interval", default=10, type=int, help="Poll interval (s)")
    parser.add_argument("--poll-timeout",  default=600, type=int, help="Poll timeout (s)")
    parser.add_argument("--ontap-cli",     default="ssh",    help="CLI tool (ssh/rsh)")
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Enable DEBUG logging"
    )
    return parser.parse_known_args()


if __name__ == "__main__":
    args, remaining = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Push CLI overrides into DEFAULT_CONFIG so test cases pick them up
    DEFAULT_CONFIG["node1"]["host"]    = args.node1_host
    DEFAULT_CONFIG["node1"]["vol"]     = args.node1_vol
    DEFAULT_CONFIG["node1"]["vserver"] = args.node1_vserver
    DEFAULT_CONFIG["node1"]["user"]    = args.node1_user
    DEFAULT_CONFIG["node2"]["host"]    = args.node2_host
    DEFAULT_CONFIG["node2"]["vol"]     = args.node2_vol
    DEFAULT_CONFIG["node2"]["vserver"] = args.node2_vserver
    DEFAULT_CONFIG["node2"]["user"]    = args.node2_user
    DEFAULT_CONFIG["poll_interval"]    = args.poll_interval
    DEFAULT_CONFIG["poll_timeout"]     = args.poll_timeout
    DEFAULT_CONFIG["ontap_cli"]        = args.ontap_cli

    # Run unittest with the remaining argv (supports -k, -v, etc.)
    unittest.main(argv=[sys.argv[0]] + remaining)
