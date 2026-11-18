"""Offline, end-to-end CLI/IPAM tests. Fake 'ip' responds with no links."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

EXE = Path(__file__).resolve().parents[1] / "gre6ctl"


class CliScenario(unittest.TestCase):
    def test_one_hub_many_spokes_import_and_conflict(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            bindir = base / "bin"
            bindir.mkdir()
            ip = bindir / "ip"
            ip.write_text("""#!/bin/sh
case "$*" in
  '-j -4 addr show') echo '[{"ifname":"eth0","addr_info":[{"family":"inet","local":"198.51.100.4","prefixlen":24}]}]' ;;
  '-j -4 route show table all') echo '[{"dst":"198.51.100.0/24","dev":"eth0"}]' ;;
  '-d -j link show dev '*) exit 1 ;;
  *) echo "Unexpected mock ip request: $*" >&2; exit 2 ;;
esac
""")
            ip.chmod(0o755)
            env = os.environ.copy()
            env["PATH"] = str(bindir) + os.pathsep + env["PATH"]
            env["GRE6CTL_BASE"] = str(base / "hub")
            def run(*args, ok=True, stdin=None):
                p = subprocess.run([str(EXE), *args], text=True, env=env,
                                   capture_output=True, timeout=8, input=stdin)
                if ok:
                    self.assertEqual(p.returncode, 0, p.stderr)
                else:
                    self.assertNotEqual(p.returncode, 0, p.stdout)
                return p
            for n in range(1, 4):
                run("create", f"iran{n}", "--local6", "2606:4700::1",
                    "--peer6", f"2606:4700::{100+n}", "--accept-auto")
            saved = [json.loads((base / "hub/tunnels" / f"iran{n}.json").read_text()) for n in range(1, 4)]
            self.assertEqual([x["subnet"] for x in saved],
                             ["10.250.0.0/30", "10.200.0.0/30", "10.150.0.0/30"])
            self.assertIn("10.100.0.1", run("ipam").stdout)
            self.assertIn("collision", run("create", "bad", "--local6", "2606:4700::1",
                     "--peer6", "2606:4700::115", "--subnet", "10.200.0.0/30", ok=False).stderr)
            run("create", "custom", "--local6", "2606:4700::1",
                "--peer6", "2606:4700::116", "--local-ip", "10.80.4.2", "--peer-ip", "10.80.4.1")
            # Interactive default acceptance: 4th tunnel gets 10.100.*.
            accepted = run("create", "iran4", "--local6", "2606:4700::1",
                           "--peer6", "2606:4700::117", stdin="y\n")
            self.assertIn("Suggested private IPv4s", accepted.stdout)
            self.assertIn("10.100.0.1", accepted.stdout)
            self.assertEqual(json.loads((base / "hub/tunnels/iran4.json").read_text())["peer4"],
                             "10.100.0.2")
            # User declines 5th suggestion and chooses manual, reversed .1/.2 pair.
            custom = run("create", "iran5", "--local6", "2606:4700::1",
                         "--peer6", "2606:4700::118", stdin="n\npair\n10.80.9.2\n10.80.9.1\n")
            self.assertIn("10.50.0.1", custom.stdout)
            saved_custom = json.loads((base / "hub/tunnels/iran5.json").read_text())
            self.assertEqual((saved_custom["local4"], saved_custom["peer4"]),
                             ("10.80.9.2", "10.80.9.1"))
            self.assertEqual(saved_custom["subnet"], "10.80.9.0/30")
            # Invalid custom pair is rejected; no JSON should be created.
            invalid = run("create", "broken", "--local6", "2606:4700::1",
                          "--peer6", "2606:4700::119", ok=False,
                          stdin="n\npair\n10.80.10.1\n10.80.10.5\n")
            self.assertIn("two usable hosts", invalid.stderr)
            self.assertFalse((base / "hub/tunnels/broken.json").exists())
            # Refuse silent auto-allocation with redirected stdin / EOF.
            missing = run("create", "unapproved", "--local6", "2606:4700::1",
                          "--peer6", "2606:4700::120", ok=False, stdin="")
            self.assertIn("--accept-auto", missing.stderr)
            self.assertFalse((base / "hub/tunnels/unapproved.json").exists())
            # Explicitly requested manual /30 avoids confirmation prompt.
            run("create", "explicit", "--local6", "2606:4700::1",
                "--peer6", "2606:4700::121", "--subnet", "10.80.20.0/30")
            token = run("export-peer", "iran2").stdout.strip()
            env["GRE6CTL_BASE"] = str(base / "spoke")
            run("import-peer", token)
            remote = json.loads((base / "spoke/tunnels/iran2.json").read_text())
            self.assertEqual(remote["local4"], "10.200.0.2")
            self.assertEqual(remote["peer4"], "10.200.0.1")
            self.assertEqual(remote["local6"], saved[1]["peer6"])
            self.assertEqual(remote["peer6"], saved[1]["local6"])
            self.assertIn("iran2", run("list").stdout)

if __name__ == "__main__":
    unittest.main()
