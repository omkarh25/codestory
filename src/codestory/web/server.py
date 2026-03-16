"""
HTMX web server for codeStory public repos.

Serves the noir-themed web interface for viewing public repo haikus.
"""

import os
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core import DatabaseManager
from codestory.core.logging import get_logger
from codestory.core.public_repo import (
    get_public_repo,
    list_public_repos,
    get_repo_db_path,
)
from codestory.render.htmx import render_index, render_repo_page

LOGGER = get_logger(__name__)


class CodeStoryHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for codeStory HTMX pages."""
    
    def do_GET(self):
        """Handle GET requests."""
        # Parse path
        path = self.path.strip("/")
        
        if path == "" or path == "/":
            # Home page - list all repos
            repos = list_public_repos()
            html = render_index(repos)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            
        elif path.startswith("repo/"):
            # Repo detail page
            slug = path.replace("repo/", "").strip("/")
            
            # Get repo
            repo = get_public_repo(slug)
            if not repo:
                self.send_error(404, f"Repo not found: {slug}")
                return
            
            # Get haikus from repo DB
            db_path = get_repo_db_path(slug)
            haikus = []
            episodes = []
            
            if db_path.exists():
                try:
                    db = DatabaseManager(str(db_path))
                    haikus = db.get_all_haikus()
                    episodes = db.get_all_episodes()
                except Exception as e:
                    LOGGER.warning(f"Failed to load DB for {slug}: {e}")
            
            html = render_repo_page(slug, haikus, episodes)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            
        else:
            # Static files or 404
            self.send_error(404, "Not Found")
    
    def log_message(self, format, *args):
        """Log HTTP requests."""
        LOGGER.info(f"{self.address_string()} - {format % args}")


def start_server(port: int = 8080) -> None:
    """
    Start the HTMX web server.
    
    Args:
        port: Port to listen on
    """
    server_address = ('', port)
    httpd = HTTPServer(server_address, CodeStoryHandler)
    
    print(f"\n🎭 codeStory HTMX Server")
    print(f"   ════════════════════════════")
    print(f"   🌐 http://localhost:{port}")
    print(f"   📚 Public repos: {len(list_public_repos())}")
    print(f"   ════════════════════════════")
    print(f"\n   Press Ctrl+C to stop\n")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n👋 Server stopped.")
        httpd.shutdown()


def run_server(port: int = 8080) -> None:
    """Run the server (entry point)."""
    start_server(port)


if __name__ == "__main__":
    start_server()
