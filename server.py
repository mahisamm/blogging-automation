"""
=============================================================================
WealthMarg Auto Blog Publisher - server.py (Dashboard + API)
=============================================================================
Run this file to start the dashboard at http://localhost:8000
It also handles triggering workflow runs on demand.
=============================================================================
"""
import http.server
import socketserver
import json
import os
import sys
import threading

# Make sure we can import from the same folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import state_manager

PORT = 8000

def run_workflow_in_thread():
    """Run the full publish workflow in a background thread."""
    try:
        import importlib
        # Force reimport in case module was cached
        if 'auto_publisher' in sys.modules:
            del sys.modules['auto_publisher']
        import auto_publisher
        auto_publisher.run_publish_workflow()
    except Exception as e:
        import traceback
        err = traceback.format_exc()
        print(f"[WORKFLOW ERROR] {err}")
        state_manager.end_run(error=str(e))


class DashboardHandler(http.server.SimpleHTTPRequestHandler):

    def log_message(self, format, *args):
        # Suppress request logs to keep terminal clean
        pass

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == '/' or self.path == '/index.html':
            self.send_response(200)
            self.send_header('Content-type', 'text/html; charset=utf-8')
            self.end_headers()
            html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'index.html')
            with open(html_path, 'rb') as f:
                self.wfile.write(f.read())

        elif self.path == '/api/status':
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            state = state_manager.read_state()
            self.wfile.write(json.dumps(state).encode())

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'Not found')

    def do_POST(self):
        if self.path == '/api/trigger':
            state = state_manager.read_state()
            if state.get('is_running'):
                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"success": False, "message": "Already running"}).encode())
                return

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"success": True, "message": "Workflow started"}).encode())

            # Run in background thread so it doesn't block the HTTP server
            t = threading.Thread(target=run_workflow_in_thread, daemon=True)
            t.start()

        else:
            self.send_response(404)
            self.end_headers()


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    print("=" * 55)
    print("  WealthMarg Dashboard & Publisher Server")
    print("=" * 55)
    print(f"  Dashboard: http://localhost:{PORT}")
    print(f"  Press Ctrl+C to stop")
    print("=" * 55)

    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), DashboardHandler) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nServer stopped.")
