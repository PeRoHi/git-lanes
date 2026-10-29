from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from launch import netstat_listening_pid


class NetstatPortTest(unittest.TestCase):
    def test_exact_listening_port(self):
        line = "  TCP    127.0.0.1:17920         0.0.0.0:0              LISTENING       4321"
        self.assertEqual(netstat_listening_pid(line, 17920), "4321")
        self.assertIsNone(netstat_listening_pid(line, 1792))
        wider = "  TCP    127.0.0.1:179201        0.0.0.0:0              LISTENING       99"
        self.assertIsNone(netstat_listening_pid(wider, 17920))
        v6 = "  TCP    [::1]:17920              [::]:0                 LISTENING       7"
        self.assertEqual(netstat_listening_pid(v6, 17920), "7")
        self.assertIsNone(netstat_listening_pid(line.replace("LISTENING", "ESTABLISHED"), 17920))
        self.assertIsNone(
            netstat_listening_pid(
                "  TCP    127.0.0.1:17920         0.0.0.0:0              LISTENING       ４２",
                17920,
            )
        )

    def test_profile_pid_lines_are_ascii_exact(self):
        from git_lanes.httpguard import parse_exact_uint

        self.assertEqual(parse_exact_uint("4321"), 4321)
        self.assertIsNone(parse_exact_uint("０"))
        self.assertIsNone(parse_exact_uint("042"))
        self.assertIsNone(parse_exact_uint(""))


if __name__ == "__main__":
    unittest.main()
