import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

from orcaslicer_matrix.studio_client import IncompatibleOrcaError, StudioClient


class Handler(BaseHTTPRequestHandler):
    capabilities = {
        "api_version": "1.1",
        "app_version": "2.6.0",
        "build_id": "test",
        "features": ["status", "config", "slice", "slice_cancel", "gcode"],
        "max_matrix_variants": 32,
        "compare_bundle_versions": [1, 2],
    }

    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.headers.get("X-Api-Token") != "test-token":
            self.send_response(401)
            self.end_headers()
            return
        if self.path == "/api/v1/capabilities":
            payload = json.dumps(self.capabilities).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(404)
        self.end_headers()


class TestStudioClient(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def test_capability_handshake(self):
        with StudioClient(self.url, "test-token") as client:
            caps = client.capabilities()
        self.assertTrue(caps.supports_matrix_studio)
        self.assertEqual(caps.max_matrix_variants, 32)
        self.assertIn(2, caps.compare_bundle_versions)

    def test_rejects_incompatible_viewer(self):
        original = Handler.capabilities
        try:
            Handler.capabilities = {**original, "compare_bundle_versions": [1]}
            with StudioClient(self.url, "test-token") as client:
                with self.assertRaises(IncompatibleOrcaError):
                    client.capabilities()
        finally:
            Handler.capabilities = original


if __name__ == "__main__":
    unittest.main()
