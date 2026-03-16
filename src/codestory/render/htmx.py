"""
HTMX renderer for codeStory public repos.

Generates HTML templates for viewing haikus and episodes in a web browser.
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger
from codestory.render.presentation import build_case_file_presentation

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

        .repo-list-shell {{
            margin-top: 1rem;
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

        .haiku-card.collapsed {{
            position: relative;
            overflow: hidden;
        }}

        .haiku-card.collapsed::before {{
            content: "";
            position: absolute;
            inset: 0;
            background: linear-gradient(90deg, transparent, rgba(255, 176, 0, 0.06), transparent);
            transform: translateX(-100%);
            transition: transform 0.5s ease;
        }}

        .haiku-card.collapsed:hover::before {{
            transform: translateX(100%);
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

        .case-pull-label {{
            color: var(--accent-amber);
            letter-spacing: 1px;
            margin-bottom: 0.6rem;
            font-size: 0.88rem;
        }}

        .loading-indicator {{
            display: none;
            margin-top: 0.8rem;
            color: var(--accent-amber);
            font-size: 0.8rem;
            letter-spacing: 1px;
            animation: blink 0.9s steps(2, start) infinite;
        }}

        .htmx-request .loading-indicator,
        .htmx-request.loading-indicator {{
            display: inline-block;
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

        .hidden {{
            opacity: 0;
            transform: translateY(6px);
        }}

        .visible {{
            opacity: 1;
            transform: translateY(0);
            transition: opacity 0.35s ease, transform 0.35s ease;
        }}

        .haiku-stage {{
            width: 100vw;
            min-height: 100vh;
            margin-left: calc(50% - 50vw);
            margin-right: calc(50% - 50vw);
            background: radial-gradient(circle at top, #171717 0%, #080808 70%);
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            position: relative;
            overflow: hidden;
            padding: 2.25rem 1.25rem;
        }}

        .haiku-stage::before {{
            content: "";
            position: absolute;
            inset: 0;
            background: repeating-linear-gradient(
                to bottom,
                rgba(255, 255, 255, 0.02),
                rgba(255, 255, 255, 0.02) 1px,
                transparent 1px,
                transparent 4px
            );
            pointer-events: none;
        }}

        .haiku-stage-inner {{
            max-width: 950px;
            margin: 0 auto;
            position: relative;
            z-index: 1;
            border: 1px solid var(--border);
            background: rgba(10, 10, 10, 0.86);
            padding: 2rem;
        }}

        .case-stage {{
            display: none;
            min-height: calc(100vh - 7rem);
        }}

        .case-stage.active {{
            display: block;
        }}

        .dramatic-title {{
            font-family: 'Special Elite', cursive;
            color: var(--accent-red);
            font-size: 1.9rem;
            margin-bottom: 0.8rem;
            min-height: 2.5rem;
        }}

        .meta-line {{
            display: flex;
            flex-wrap: wrap;
            gap: 0.6rem;
            margin: 1rem 0 1.25rem;
            font-size: 0.78rem;
            color: var(--text-secondary);
        }}

        .meta-line span {{
            border: 1px solid var(--border);
            padding: 0.2rem 0.5rem;
            background: rgba(0, 0, 0, 0.5);
        }}

        .meta-grid {{
            margin: 1rem 0 1.4rem;
            border: 1px solid var(--border);
            background: rgba(4, 8, 15, 0.75);
            padding: 1rem;
        }}

        .meta-item {{
            margin-bottom: 0.45rem;
            font-size: 0.95rem;
        }}

        .meta-key {{
            color: #8aaccc;
            font-weight: bold;
            margin-right: 0.35rem;
        }}

        .meta-value {{
            color: #c8ddf0;
        }}

        .meta-code {{
            color: #6abf69;
            font-family: Menlo, Monaco, monospace;
        }}

        .act-screen {{
            padding-top: 4vh;
        }}

        .verdict-screen {{
            display: flex;
            align-items: center;
            justify-content: center;
        }}

        .verdict-panel {{
            width: min(100%, 920px);
            border: 1px solid var(--border);
            background: rgba(6, 10, 18, 0.86);
            padding: 2rem;
        }}

        .verdict-label {{
            color: var(--accent-red);
            font-family: 'Special Elite', cursive;
            font-size: 1.2rem;
            margin-bottom: 0.8rem;
        }}

        .stage-hint {{
            margin-top: 1rem;
            color: var(--text-secondary);
            font-size: 0.8rem;
            letter-spacing: 0.8px;
            text-transform: uppercase;
        }}

        .verdict.stamped {{
            box-shadow: 0 0 0 1px rgba(196, 30, 58, 0.4), 0 0 20px rgba(196, 30, 58, 0.25);
            transform: scale(1.01);
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

        @keyframes blink {{
            50% {{ opacity: 0.35; }}
        }}

        @media (max-width: 760px) {{
            .container {{
                padding: 1.2rem;
            }}

            .haiku-stage-inner {{
                padding: 1.2rem;
            }}

            .dramatic-title {{
                font-size: 1.45rem;
            }}
        }}
    </style>
    <script>
        function typeWriter(element, speed = 28) {{
            const text = element.dataset.fullText || element.textContent || "";
            element.dataset.fullText = text;
            element.textContent = "";
            let idx = 0;

            const tick = () => {{
                if (idx < text.length) {{
                    element.textContent += text.charAt(idx);
                    idx += 1;
                    setTimeout(tick, speed);
                }}
            }};

            tick();
        }}

        function stampVerdict(element) {{
            element.classList.add('stamped');
        }}

        function revealStage(container, index) {{
            const stages = container.querySelectorAll('.case-stage');
            if (!stages.length || index < 0 || index >= stages.length) {{
                return;
            }}

            stages.forEach((stage) => stage.classList.remove('active'));
            const nextStage = stages[index];
            nextStage.classList.add('active');

            const typeNodes = nextStage.querySelectorAll('[data-typewriter="true"]');
            typeNodes.forEach((el) => {{
                if (el.dataset.typed === 'true') {{
                    return;
                }}
                el.dataset.typed = 'true';
                typeWriter(el);
            }});

            const verdict = nextStage.querySelector('.verdict');
            if (verdict) {{
                stampVerdict(verdict);
            }}
        }}

        function advanceCaseStage(container) {{
            if (!container) {{
                return;
            }}

            const current = Number(container.dataset.stageIndex || '0');
            const next = current + 1;
            const stageCount = container.querySelectorAll('.case-stage').length;
            if (next >= stageCount) {{
                return;
            }}

            container.dataset.stageIndex = String(next);
            revealStage(container, next);
        }}

        function initializeCaseStage(container) {{
            if (!container || container.dataset.staged === 'true') {{
                return;
            }}

            container.dataset.staged = 'true';
            container.dataset.stageIndex = '0';
            revealStage(container, 0);
            container.focus();

            container.addEventListener('click', () => {{
                advanceCaseStage(container);
            }});
        }}

        document.addEventListener('keydown', (event) => {{
            if (event.code !== 'Space') {{
                return;
            }}

            const active = document.querySelector('.haiku-stage[data-staged="true"]');
            if (!active) {{
                return;
            }}

            event.preventDefault();
            advanceCaseStage(active);
        }});
    </script>
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
    
    <div class="repo-list-shell" hx-boost="true">
        <ul class="repo-list">
            {repos_html or "<li>No public repos tracked yet.</li>"}
        </ul>
    </div>
    
    <p style="margin-top: 2rem; color: var(--text-secondary);">
        Add a public repo: <code>codestory --add-public-repo https://github.com/owner/repo</code>
    </p>
    """
    
    return BASE_TEMPLATE.format(title="Home", content=content)


def render_repo_page(slug: str, haikus: List[Dict[str, Any]], episodes: List[Dict[str, Any]]) -> str:
    """Render a repo detail page with haikus."""
    # Render haiku cards
    haikus_html = ""
    for index, haiku in enumerate(haikus):
        h_title = haiku.get("title", "Untitled")
        h_subtitle = haiku.get("subtitle", "")
        h_date = haiku.get("commit_date", "")[:10]
        h_branch = haiku.get("branch", "main")
        h_type = haiku.get("commit_type", "other")

        haikus_html += f"""
        <div class="haiku-card collapsed"
             hx-get="/repo/{slug}/haiku/{index}/full"
             hx-trigger="click once"
             hx-swap="outerHTML"
             hx-indicator="#loading-{index}"
             hx-transition="true"
             role="button"
             tabindex="0"
             aria-label="Open case file {index + 1}">
            <div class="case-pull-label">▶ CASE FILE — Click to Unseal</div>
            <div class="haiku-title">{h_title}</div>
            <div class="haiku-subtitle">{h_subtitle}</div>
            <div class="haiku-meta">
                <span>{h_date}</span>
                <span>{h_branch}</span>
                <span>{h_type}</span>
            </div>
            <span id="loading-{index}" class="loading-indicator htmx-indicator">[ ACCESSING FILE... ]</span>
        </div>
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


def render_haiku_fullscreen_fragment(
    slug: str,
    index: int,
    total: int,
    haiku: Dict[str, Any],
) -> str:
    """Render one full-screen dramatic haiku fragment for HTMX swaps."""
    case = build_case_file_presentation(haiku, index + 1, total)

    return f"""
    <section class="haiku-stage"
             tabindex="0"
             hx-on::after-settle="initializeCaseStage(this)">
        <div class="haiku-stage-inner">
            <div class="case-stage stage-header active">
                <div class="case-pull-label">Case {case["case_number"]} of {case["total_cases"]} • {case["short_hash"]} • {case["branch"]} • {case["formatted_date"]}</div>
                <h2 class="dramatic-title" data-typewriter="true">{case["title"]}</h2>
                <p class="haiku-subtitle">{case["subtitle"]}</p>

                <div class="meta-grid">
                    <div class="meta-item"><span class="meta-key">Date:</span> <span class="meta-value">{case["formatted_date"]}</span></div>
                    <div class="meta-item"><span class="meta-key">Commit:</span> <span class="meta-code">{case["commit_msg"]}</span></div>
                    <div class="meta-item"><span class="meta-key">Branch:</span> <span class="meta-code">{case["branch"]}</span></div>
                    <div class="meta-item"><span class="meta-key">Type:</span> <span class="meta-code">{case["commit_type_label"]}</span> <span class="meta-value">— <em>{case["crime_text"]}</em></span></div>
                    <div class="meta-item"><span class="meta-key">Author:</span> <span class="meta-value">{case["author"]}</span></div>
                </div>
                <div class="stage-hint">[ SPACE ] reveal Act I</div>
            </div>

            <div class="case-stage act-screen">
                <div class="act-title" data-typewriter="true">Act I: {case["act1_title"]}</div>
                <div class="act-content">{case["when_where"]}</div>
                <div class="stage-hint">[ SPACE ] reveal Act II</div>
            </div>

            <div class="case-stage act-screen">
                <div class="act-title" data-typewriter="true">Act II: {case["act2_title"]}</div>
                <div class="act-content">{case["who_whom"]}</div>
                <div class="stage-hint">[ SPACE ] reveal Act III</div>
            </div>

            <div class="case-stage act-screen">
                <div class="act-title" data-typewriter="true">Act III: {case["act3_title"]}</div>
                <div class="act-content">{case["what_why"]}</div>
                <div class="stage-hint">[ SPACE ] reveal Verdict</div>
            </div>

            <div class="case-stage verdict-screen">
                <div class="verdict-panel">
                    <div class="verdict-label" data-typewriter="true">🔑 VERDICT</div>
                    <div class="verdict">{case["verdict"]}</div>
                    <div class="stage-hint">Final screen reached</div>
                </div>
            </div>
        </div>
    </section>
    """
