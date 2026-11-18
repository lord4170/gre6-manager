import importlib.machinery
import importlib.util
from pathlib import Path
import argparse
import contextlib
import io
import unittest
from unittest import mock

path = Path(__file__).resolve().parents[1] / 'gre6ctl'
loader = importlib.machinery.SourceFileLoader('gre6_wizard', str(path))
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)


class WizardTests(unittest.TestCase):
    def test_ipv6_candidates_prefer_default_route_and_skip_tentative(self):
        addresses = [
            {'ifname': 'eth1', 'addr_info': [{'family':'inet6','local':'2606:4700::20'}]},
            {'ifname': 'eth0', 'addr_info': [
                {'family':'inet6','local':'fe80::1'},
                {'family':'inet6','local':'2606:4700::1'},
                {'family':'inet6','local':'2606:4700::2', 'flags':['tentative']},
            ]},
        ]
        route = mock.Mock(returncode=0, stdout='[{"dev":"eth0"}]')
        with mock.patch.object(m, 'require_ip'), mock.patch.object(m,'jrun',return_value=addresses), mock.patch.object(m,'run',return_value=route):
            self.assertEqual(m.local_ipv6_candidates(), [
                ('2606:4700::1','eth0',True),
                ('2606:4700::20','eth1',False)
            ])

    def test_confirm_local_ipv6_and_manual_override(self):
        with mock.patch.object(m,'local_ipv6_candidates',return_value=[('2606:4700::1','eth0',True)]), mock.patch.object(m,'ui_confirm',return_value=True):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.ui_pick_local_ipv6(),'2606:4700::1')
        with mock.patch.object(m,'local_ipv6_candidates',return_value=[('2606:4700::1','eth0',True)]), mock.patch.object(m,'ui_confirm',side_effect=[False, True]), mock.patch.object(m,'prompt',side_effect=['m','2606:4700::3']):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(m.ui_pick_local_ipv6(),'2606:4700::3')

    def test_import_rejects_mismatched_local_ipv6_without_saving(self):
        cfg = m.make_config('iran1','2606:4700::1','2606:4700::2','10.250.0.0/30')
        token = m.peer_token(cfg)
        with mock.patch.object(m,'prompt',return_value=token), mock.patch.object(m,'ui_pick_local_ipv6',return_value='2606:4700::3'), mock.patch.object(m,'import_peer_cmd') as imp:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(m.Failure,'mismatch'):
                    m.ui_import()
            imp.assert_not_called()

    def test_creation_shows_import_token_immediately(self):
        cfg = m.make_config('iran1','2606:4700::1','2606:4700::2','10.250.0.0/30')
        with mock.patch.object(m, 'prompt',side_effect=['iran1','1400']), mock.patch.object(m,'ui_pick_local_ipv6',return_value=cfg['local6']), mock.patch.object(m,'ui_pick_remote_ipv6',return_value=cfg['peer6']), mock.patch.object(m,'create_cmd'), mock.patch.object(m,'ui_confirm',return_value=False), mock.patch.object(m,'load',return_value=cfg):
            buf=io.StringIO()
            with contextlib.redirect_stdout(buf):
                m.ui_create()
            self.assertIn(m.peer_token(cfg),buf.getvalue())
            self.assertIn('REMOTE SERVER CONFIGURATION',buf.getvalue())

    def test_menu_prompts_for_role(self):
        with mock.patch.object(m,'root'),mock.patch.object(m,'ui_select_role',return_value=None),mock.patch.object(m,'ui_dashboard') as dashboard:
            m.menu_cmd(None)
            dashboard.assert_not_called()

if __name__ == '__main__':
    unittest.main()
