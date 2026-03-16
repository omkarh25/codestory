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
from codestory.render.htmx import (
    render_haiku_fullscreen_fragment,
    render_index,
    render_repo_page,
)

LOGGER = get_logger(__name__)


class CodeStoryHandler(SimpleHTTPRequestHandler):
    """HTTP request handler for codeStory HTMX pages."""
    
    def do_GET(self):
        """Handle GET requests."""
        # Parse path
        path = self.path.split("?", 1)[0].strip("/")
        
        if path == "" or path == "/":
            # Home page - list all repos
            repos = list_public_repos()
            html = render_index(repos)
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(html.encode())
            
        elif path.startswith("repo/") and "/haiku/" in path and path.endswith("/full"):
            # HTMX haiku fullscreen fragment
            parts = path.split("/")
            # Expected: repo/{slug}/haiku/{index}/full
            if len(parts) < 5 or parts[2] != "haiku" or parts[4] != "full":
                self.send_error(404, "Invalid haiku route")
                return

            slug = parts[1]
            try:
                haiku_index = int(parts[3])
            except ValueError:
                self.send_error(400, "Invalid haiku index")
                return

            repo = get_public_repo(slug)
            if not repo:
                self.send_error(404, f"Repo not found: {slug}")
                return

            db_path = get_repo_db_path(slug)
            haikus = []
            if db_path.exists():
                try:
                    db = DatabaseManager(str(db_path))
                    haikus = db.get_all_haikus()
                except Exception as e:
                    LOGGER.warning("Failed to load DB for %s: %s", slug, e)
                    self.send_error(500, "Failed to load haikus")
                    return

            if not haikus:
                self.send_error(404, "No haikus found")
                return
            if haiku_index < 0 or haiku_index >= len(haikus):
                self.send_error(404, f"Haiku index out of range: {haiku_index}")
                return

            html = render_haiku_fullscreen_fragment(
                slug=slug,
                index=haiku_index,
                total=len(haikus),
                haiku=haikus[haiku_index],
            )
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
                    LOGGER.warning("Failed to load DB for %s: %s", slug, e)
            
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
    
    LOGGER.info("\n🎭 codeStory HTMX Server")
    LOGGER.info("   ════════════════════════════")
    LOGGER.info("   🌐 http://localhost:%s", port)
    LOGGER.info("   📚 Public repos: %d", len(list_public_repos()))
    LOGGER.info("   ════════════════════════════")
    LOGGER.info("\n   Press Ctrl+C to stop\n")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOGGER.info("\n\n👋 Server stopped.")
        httpd.shutdown()


def run_server(port: int = 8080) -> None:
    """Run the server (entry point)."""
    start_server(port)


if __name__ == "__main__":
    start_server()
