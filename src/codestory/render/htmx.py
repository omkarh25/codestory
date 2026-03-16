"""
HTMX renderer for codeStory public repos.

Generates HTML templates for viewing haikus and episodes in a web browser.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)


# Base HTML template with noir styling
BASE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} | codeStory</title>
    <script src="https://unpkg.com/htmx.org@1.9.10"></script>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Special+Elite&family=Courier+Prime&display=swap');
        
        :root {{
            --bg-dark: #0a0a0a;
            --bg-panel: #141414;
            --text-primary: #e8e8e8;
            --text-secondary: #888;
            --accent-amber: #ffb000;
            --accent-red: #c41e3a;
            --border: #2a2a2a;
        }}
        
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        
        body {{
            background: var(--bg-dark);
            color: var(--text-primary);
            font-family: 'Courier Prime', monospace;
            line-height: 1.6;
            min-height: 100vh;
        }}
        
        .container {{
            max-width: 900px;
            margin: 0 auto;
            padding: 2rem;
        }}
        
        header {{
            border-bottom: 1px solid var(--border);
            padding-bottom: 1rem;
            margin-bottom: 2rem;
        }}
        
        h1 {{
            font-family: 'Special Elite', cursive;
            color: var(--accent-amber);
            font-size: 1.8rem;
            letter-spacing: 2px;
        }}
        
        .subtitle {{
            color: var(--text-secondary);
            font-size: 0.9rem;
            margin-top: 0.5rem;
        }}
        
        nav {{
            display: flex;
            gap: 1.5rem;
            margin: 1.5rem 0;
            border-bottom: 1px solid var(--border);
            padding-bottom: 1rem;
        }}
        
        nav a {{
            color: var(--text-secondary);
            text-decoration: none;
            transition: color 0.2s;
        }}
        
        nav a:hover, nav a.htmx-request {{
            color: var(--accent-amber);
        }}
        
        .haiku-card {{
            background: var(--bg-panel);
            border: 1px solid var(--border);
            padding: 1.5rem;
            margin-bottom: 1.5rem;
            cursor: pointer;
            transition: border-color 0.2s;
        }}
        
        .haiku-card:hover {{
            border-color: var(--accent-amber);
        }}
        
        .haiku-title {{
            font-family: 'Special Elite', cursive;
            color: var(--accent-red);
            font-size: 1.1rem;
            margin-bottom: 0.5rem;
        }}
        
        .haiku-subtitle {{
            color: var(--text-secondary);
            font-size: 0.85rem;
            font-style: italic;
            margin-bottom: 1rem;
        }}
        
        .haiku-meta {{
            display: flex;
            gap: 1rem;
            font-size: 0.8rem;
            color: var(--text-secondary);
        }}
        
        .haiku-meta span {{
            background: var(--bg-dark);
            padding: 0.2rem 0.5rem;
        }}
        
        .haiku-detail {{
            display: none;
            margin-top: 1.5rem;
            padding-top: 1.5rem;
            border-top: 1px solid var(--border);
        }}
        
        .haiku-card[open] .haiku-detail {{
            display: block;
        }}
        
        .act-title {{
            font-family: 'Special Elite', cursive;
            color: var(--accent-amber);
            margin: 1rem 0 0.5rem;
        }}
        
        .act-content {{
            color: var(--text-primary);
            margin-bottom: 1rem;
        }}
        
        .verdict {{
            font-family: 'Special Elite', cursive;
            color: var(--accent-red);
            font-size: 1.2rem;
            text-align: center;
            padding: 1rem;
            border: 1px solid var(--accent-red);
            margin-top: 1.5rem;
        }}
        
        .repo-list {{
            list-style: none;
        }}
        
        .repo-item {{
            display: flex;
            justify-content: space-between;
            padding: 1rem;
            background: var(--bg-panel);
            margin-bottom: 0.5rem;
            border: 1px solid var(--border);
        }}
        
        .repo-item a {{
            color: var(--accent-amber);
            text-decoration: none;
        }}
        
        .status {{
            font-size: 0.8rem;
            padding: 0.2rem 0.5rem;
            background: var(--bg-dark);
        }}
        
        .status.ready {{ color: #4caf50; }}
        .status.pending {{ color: var(--accent-amber); }}
        
        footer {{
            margin-top: 3rem;
            padding-top: 1rem;
            border-top: 1px solid var(--border);
            text-align: center;
            color: var(--text-secondary);
            font-size: 0.8rem;
        }}
    </style>
</head>
<body hx-boost="true">
    <div class="container">
        <header>
            <h1>⚡ codeStory</h1>
            <p class="subtitle">Every commit is a confession. Every repo is a crime scene.</p>
        </header>
        
        {content}
        
        <footer>
            <p>Generated by codeStory • Public Repo Archives</p>
        </footer>
    </div>
</body>
</html>
"""


def render_index(public_repos: List[Dict[str, Any]]) -> str:
    """Render the index page with list of repos."""
    repos_html = ""
    for repo in public_repos:
        slug = repo.get("slug", "")
        url = repo.get("url", "")
        status = repo.get("status", "unknown")
        tags = repo.get("tags", [])
        
        repos_html += f"""
        <li class="repo-item">
            <div>
                <a href="/repo/{slug}">{slug}</a>
                <span class="status {status}">{status}</span>
            </div>
            <div>
                {" ".join(f"<span>#{tag}</span>" for tag in tags)}
            </div>
        </li>
        """
    
    content = f"""
    <nav>
        <a href="/">Home</a>
    </nav>
    
    <h2>📚 Public Repositories</h2>
    
    <ul class="repo-list">
        {repos_html or "<li>No public repos tracked yet.</li>"}
    </ul>
    
    <p style="margin-top: 2rem; color: var(--text-secondary);">
        Add a public repo: <code>codestory --add-public-repo https://github.com/owner/repo</code>
    </p>
    """
    
    return BASE_TEMPLATE.format(title="Home", content=content)


def render_repo_page(slug: str, haikus: List[Dict[str, Any]], episodes: List[Dict[str, Any]]) -> str:
    """Render a repo detail page with haikus."""
    # Render haiku cards
    haikus_html = ""
    for haiku in haikus:
        h_title = haiku.get("title", "Untitled")
        h_subtitle = haiku.get("subtitle", "")
        h_date = haiku.get("commit_date", "")[:10]
        h_branch = haiku.get("branch", "main")
        h_type = haiku.get("commit_type", "other")
        
        # Get act content
        act1_title = haiku.get("act1_title", "")
        when_where = haiku.get("when_where", "")
        act2_title = haiku.get("act2_title", "")
        who_whom = haiku.get("who_whom", "")
        act3_title = haiku.get("act3_title", "")
        what_why = haiku.get("what_why", "")
        verdict = haiku.get("verdict", "")
        
        haikus_html += f"""
        <details class="haiku-card">
            <summary>
                <div class="haiku-title">{h_title}</div>
                <div class="haiku-subtitle">{h_subtitle}</div>
                <div class="haiku-meta">
                    <span>{h_date}</span>
                    <span>{h_branch}</span>
                    <span>{h_type}</span>
                </div>
            </summary>
            <div class="haiku-detail">
                <div class="act-title">Act I: {act1_title}</div>
                <div class="act-content">{when_where}</div>
                
                <div class="act-title">Act II: {act2_title}</div>
                <div class="act-content">{who_whom}</div>
                
                <div class="act-title">Act III: {act3_title}</div>
                <div class="act-content">{what_why}</div>
                
                <div class="verdict">{verdict}</div>
            </div>
        </details>
        """
    
    if not haikus_html:
        haikus_html = "<p>No haikus generated yet. Run: codestory --public-repo {slug} --generate-haikus</p>"
    
    content = f"""
    <nav>
        <a href="/">← Back to Home</a>
    </nav>
    
    <h2>📂 {slug}</h2>
    
    <h3>🎭 Haikus ({len(haikus)})</h3>
    {haikus_html}
    
    <h3 style="margin-top: 2rem;">🎬 Episodes ({len(episodes)})</h3>
    <p style="color: var(--text-secondary);">Coming soon...</p>
    """
    
    return BASE_TEMPLATE.format(title=slug, content=content)


def render_haiku_detail(haiku: Dict[str, Any]) -> str:
    """Render a single haiku as HTML fragment."""
    h_title = haiku.get("title", "Untitled")
    h_subtitle = haiku.get("subtitle", "")
    h_date = haiku.get("commit_date", "")
    h_branch = haiku.get("branch", "main")
    h_author = haiku.get("author", "")
    h_msg = haiku.get("commit_msg", "")
    
    act1_title = haiku.get("act1_title", "")
    when_where = haiku.get("when_where", "")
    act2_title = haiku.get("act2_title", "")
    who_whom = haiku.get("who_whom", "")
    act3_title = haiku.get("act3_title", "")
    what_why = haiku.get("what_why", "")
    verdict = haiku.get("verdict", "")
    
    return f"""
    <div class="haiku-detail">
        <h3>{h_title}</h3>
        <p class="haiku-subtitle">{h_subtitle}</p>
        
        <div class="haiku-meta">
            <span>{h_date}</span>
            <span>{h_branch}</span>
            <span>{h_author}</span>
        </div>
        
        <p style="margin: 1rem 0; color: var(--text-secondary);">{h_msg}</p>
        
        <div class="act-title">Act I: {act1_title}</div>
        <div class="act-content">{when_where}</div>
        
        <div class="act-title">Act II: {act2_title}</div>
        <div class="act-content">{who_whom}</div>
        
        <div class="act-title">Act III: {act3_title}</div>
        <div class="act-content">{what_why}</div>
        
        <div class="verdict">{verdict}</div>
    </div>
    """
