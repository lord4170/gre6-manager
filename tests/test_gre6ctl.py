import importlib.machinery
import importlib.util
import ipaddress
from pathlib import Path
import tempfile
import unittest
from unittest import mock

FILE = Path(__file__).resolve().parents[1] / "gre6ctl"
loader = importlib.machinery.SourceFileLoader("gre6_manager", str(FILE))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


def config(name="iran1", subnet="10.250.0.0/30", local="2606:4700::1", peer="2606:4700::2"):
    return m.make_config(name, local, peer, subnet)


class Gre6Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        base = Path(self.temp.name)
        for name, value in (("BASE", base / "etc"), ("TUNNELS", base / "etc/tunnels"),
                            ("LOCK", base / "etc/.lock"), ("UNIT", base / "units/gre6ctl@.service"),
                            ("BIN", base / "bin/gre6ctl")):
            patch = mock.patch.object(m, name, value)
            patch.start()
            self.addCleanup(patch.stop)

    def test_auto_allocator_uses_distinct_second_octets_then_round_robin(self):
        configs = []
        expected = ["10.250.0.0/30", "10.200.0.0/30", "10.150.0.0/30",
                    "10.100.0.0/30", "10.50.0.0/30", "10.250.0.4/30",
                    "10.200.0.4/30"]
        for n, subnet in enumerate(expected, 1):
            self.assertEqual(m.next_subnet(configs, []), subnet)
            configs.append(config(f"iran{n}", subnet, "2606:4700::1", f"2606:4700::{100+n}"))

    def test_auto_next_subnet_skips_used_and_overlapping_kernel_network(self):
        c = config()
        kernel = [(ipaddress.IPv4Network("10.200.0.0/24"), "existing route")]
        self.assertEqual(m.next_subnet([c], kernel), "10.150.0.0/30")

    def test_custom_ips_work_outside_automatic_pools(self):
        cfg = m.make_config("iran3", "2606:4700::1", "2606:4700::3", "10.80.4.0/30",
                            "10.80.4.2", "10.80.4.1")
        self.assertEqual(cfg["local4"], "10.80.4.2")
        self.assertEqual(cfg["peer4"], "10.80.4.1")
        m.assert_available(cfg, [config()], [])

    def test_reverse_pair_and_token_roundtrip(self):
        c = config()
        with mock.patch.object(m, "load", return_value=c), mock.patch("builtins.print") as out:
            m.export_peer_cmd(m.arg_name("iran1"))
            token = out.call_args_list[0].args[0]
        peer = m.decode_peer(token)
        self.assertEqual(peer["local4"], c["peer4"])
        self.assertEqual(peer["peer4"], c["local4"])
        self.assertEqual(peer["local6"], c["peer6"])
        self.assertEqual(peer["peer6"], c["local6"])

    def test_subnet_collision_and_duplicate_endpoints(self):
        c = config()
        other = config("iran2", "10.250.0.0/30", "2606:4700::3", "2606:4700::4")
        with self.assertRaisesRegex(m.Failure, "collision"):
            m.assert_available(other, [c], [])
        third = config("iran2", "10.250.0.4/30")
        with self.assertRaisesRegex(m.Failure, "Duplicate GRE"):
            m.assert_available(third, [c], [])
        distinct = config("iran2", "10.250.0.4/30", "2606:4700::1", "2606:4700::4")
        m.assert_available(distinct, [c], [])

    def test_reject_wrong_or_public_ipv4_pair(self):
        with self.assertRaises(m.Failure):
            m.make_config("iran1", "2606:4700::1", "2606:4700::2", "10.250.0.0/30", "10.250.0.1", "10.250.0.5")
        with self.assertRaises(m.Failure):
            m.make_config("iran1", "2606:4700::1", "2606:4700::2", "8.8.8.0/30")
        with self.assertRaises(m.Failure):
            m.make_config("iran1", "2606:4700::1", "2606:4700::2", "10.250.0.1/30")

    def test_save_load_persistent_and_reject_untrusted_interface_names(self):
        c = config()
        m.prepare()
        m.save(c)
        self.assertEqual(m.load("iran1"), c)
        with self.assertRaises(m.Failure):
            m.valid_name("eth0;rm -rf")
        self.assertEqual((m.TUNNELS / "iran1.json").stat().st_mode & 0o777, 0o600)

    def test_refuse_kernel_route_overlap(self):
        c = config("iran1", "10.250.3.0/30")
        with self.assertRaisesRegex(m.Failure, "collision"):
            m.assert_available(c, [], [(ipaddress.IPv4Network("10.250.3.0/24"), "route")])

    def test_import_changes_side_and_preserves_existing_when_update_missing(self):
        c = config()
        token_cfg = dict(c)
        token_cfg["local4"], token_cfg["peer4"] = c["peer4"], c["local4"]
        token_cfg["local6"], token_cfg["peer6"] = c["peer6"], c["local6"]
        with mock.patch.object(m, "ipv4_kernel_networks", return_value=[]), mock.patch.object(m, "get_link", return_value=None), mock.patch.object(m, "root"):
            m.replace_config(token_cfg)
            self.assertEqual(m.load("iran1")["local4"], "10.250.0.2")
            with self.assertRaisesRegex(m.Failure, "exists"):
                m.replace_config(token_cfg)

    def test_edit_rejects_collision_before_persisting(self):
        c = config()
        m.save(c)
        other = config("iran2", "10.250.0.4/30", "2606:4700::3", "2606:4700::4")
        m.save(other)
        args = __import__("argparse").Namespace(name="iran1", subnet="10.250.0.4/30",
                 local_ip=None, peer_ip=None, local6=None, peer6=None, mtu=None, hoplimit=None)
        with mock.patch.object(m, "root"), mock.patch.object(m, "get_link", return_value=None), \
             mock.patch.object(m, "ipv4_kernel_networks", return_value=[]):
            with self.assertRaisesRegex(m.Failure, "collision"):
                m.edit_cmd(args)
        self.assertEqual(m.load("iran1"), c)

    def test_apply_cleans_partially_created_link_even_before_alias(self):
        c = config()
        operations = []
        def fake_run(args, check=True, capture=True):
            operations.append(tuple(args))
            if args[:6] == ["ip", "link", "set", "dev", "iran1", "alias"]:
                raise m.Failure("alias failed")
        with mock.patch.object(m, "preflight"), mock.patch.object(m, "get_link", return_value=None), mock.patch.object(m, "run", side_effect=fake_run):
            with self.assertRaisesRegex(m.Failure, "alias failed"):
                m.apply(c)
        self.assertIn(("ip", "link", "del", "dev", "iran1"), operations)

    def test_apply_never_touches_unmanaged_name(self):
        c = config()
        with mock.patch.object(m, "preflight"), mock.patch.object(m, "get_link", return_value={"ifalias": "user"}), mock.patch.object(m, "run") as runner:
            with self.assertRaisesRegex(m.Failure, "unmanaged"):
                m.apply(c)
            runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
