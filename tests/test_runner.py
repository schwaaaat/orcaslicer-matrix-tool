"""Integration tests for MatrixRunner orchestrator."""

import http.server
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict

from orcaslicer_matrix.client import OrcaClient
from orcaslicer_matrix.runner import MatrixRunner


MOCK_TOKEN = "runner-test-token"


class MockSlicerServer(http.server.BaseHTTPRequestHandler):
    config_store: Dict[str, str] = {
        "layer_height": "0.20",
        "wall_loops": "2",
        "filament_cost": "20.0",  # $20/kg
    }
    fail_variant_name: str = ""

    def log_message(self, format, *args):
        pass

    def do_GET(self):
        token = self.headers.get("X-Api-Token")
        if token != MOCK_TOKEN:
            self.send_response(401)
            self.end_headers()
            return

        path = self.path.split("?")[0]
        if path == "/api/v1/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {
                "app": "OrcaSlicer",
                "app_version": "2.4.2",
                "slice_result_valid": True,
                "presets": {
                    "print": "0.20mm Standard",
                    "printer": "Bambu Lab P1S 0.4 nozzle",
                    "filament": ["Elegoo PETG Rapid"],
                },
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/v1/objects":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            resp = {"objects": [{"id": 1, "name": "Hook.stl"}]}
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/v1/config":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"config": self.config_store}).encode("utf-8"))

        elif path == "/api/v1/slice/status":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            # 50 grams of filament -> at $20/kg = $1.00 cost
            resp = {
                "state": "done",
                "percent": 100,
                "stats": {
                    "estimated_time_seconds": 3600.0,
                    "filament_used_g": 50.0,
                },
                "warnings": [{"code": "WARN01", "message": "test warning"}],
            }
            self.wfile.write(json.dumps(resp).encode("utf-8"))

        elif path == "/api/v1/gcode":
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream")
            self.end_headers()
            self.wfile.write(b"; TEST GCODE\nM104 S220\nM140 S60\n")

        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == "/api/v1/slice":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "started"}).encode("utf-8"))
        elif self.path == "/api/v1/slice/cancel":
            self.send_response(200)
            self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_PUT(self):
        if self.path == "/api/v1/config":
            content_len = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(content_len).decode("utf-8"))
            applied = []
            errors = {}
            for k, v in body.items():
                if k == "invalid_key":
                    errors[k] = "unknown_key"
                else:
                    self.config_store[k] = str(v)
                    applied.append(k)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"applied": applied, "errors": errors}).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


class TestMatrixRunner(unittest.TestCase):
    server: http.server.HTTPServer
    server_thread: threading.Thread
    port: int

    @classmethod
    def setUpClass(cls):
        cls.server = http.server.HTTPServer(("127.0.0.1", 0), MockSlicerServer)
        cls.port = cls.server.server_port
        cls.server_thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        self.output_dir = Path(tempfile.mkdtemp(prefix="orca_test_run_"))
        self.client = OrcaClient(
            base_url=f"http://127.0.0.1:{self.port}",
            token=MOCK_TOKEN,
            timeout=5.0,
        )
        # Reset server baseline config
        MockSlicerServer.config_store = {
            "layer_height": "0.20",
            "wall_loops": "2",
            "filament_cost": "20.0",
        }

    def tearDown(self):
        shutil.rmtree(self.output_dir, ignore_errors=True)

    def test_full_run_and_manifest_schema_conformance(self):
        runner = MatrixRunner(
            client=self.client,
            output_dir=self.output_dir,
            timeout=5.0,
            non_interactive=True,
        )

        matrix = {
            "layer_height": ["0.16", "0.24"],
            "wall_loops": ["2", "3"],
        }
        # 2x2 = 4 variants
        manifest_path, manifest = runner.run(matrix)

        # 1. Verify manifest file created
        self.assertTrue(manifest_path.is_file())

        # 2. Verify manifest schema version and contract
        self.assertEqual(manifest["schema_version"], 1)
        self.assertIn("T", manifest["created_utc"])
        self.assertIn("Z", manifest["created_utc"])

        # Source block
        source = manifest["source"]
        self.assertEqual(source["app"], "OrcaSlicer")
        self.assertEqual(source["app_version"], "2.4.2")
        self.assertEqual(source["plate_objects"], ["Hook.stl"])
        self.assertEqual(source["print_preset"], "0.20mm Standard")
        self.assertEqual(source["printer_preset"], "Bambu Lab P1S 0.4 nozzle")
        self.assertEqual(source["filament_preset"], "Elegoo PETG Rapid")

        # Baseline & Matrix
        self.assertEqual(manifest["baseline"], "layer_height=0.16, wall_loops=2")
        self.assertEqual(manifest["matrix"], matrix)

        # Variants list
        variants = manifest["variants"]
        self.assertEqual(len(variants), 4)

        for v in variants:
            self.assertIn("name", v)
            self.assertIn("changes", v)
            self.assertIn("gcode_path", v)
            self.assertIn("stats", v)
            self.assertIn("warnings", v)
            self.assertIsNone(v["error"])

            # Verify stats: 50g at $20/kg -> $1.00 cost
            self.assertEqual(v["stats"]["time_s"], 3600.0)
            self.assertEqual(v["stats"]["filament_g"], 50.0)
            self.assertEqual(v["stats"]["cost_usd"], 1.00)

            # Verify G-code file was written alongside manifest
            gcode_file = self.output_dir / v["gcode_path"]
            self.assertTrue(gcode_file.is_file())
            self.assertGreater(gcode_file.stat().st_size, 0)

        # 3. CRITICAL: Verify exact configuration restoration in server
        self.assertEqual(MockSlicerServer.config_store["layer_height"], "0.20")
        self.assertEqual(MockSlicerServer.config_store["wall_loops"], "2")

    def test_snapshot_restored_even_if_error_occurs(self):
        runner = MatrixRunner(
            client=self.client,
            output_dir=self.output_dir,
            timeout=5.0,
            non_interactive=True,
        )

        matrix = {
            "layer_height": ["0.12"],
            "invalid_key": ["bad_val"],
        }
        manifest_path, manifest = runner.run(matrix)

        # Variant should have error recorded
        v0 = manifest["variants"][0]
        self.assertIsNotNone(v0["error"])
        self.assertIn("Invalid config keys", v0["error"])
        self.assertIsNone(v0["gcode_path"])

        # And configuration must still be restored
        self.assertEqual(MockSlicerServer.config_store["layer_height"], "0.20")
        self.assertEqual(MockSlicerServer.config_store["wall_loops"], "2")


if __name__ == "__main__":
    unittest.main()
