"""
Public repo management for codeStory.

Handles:
- Loading/saving publicRepos.yaml config
- Cloning/fetching GitHub public repos
- Per-repo SQLite database management
- Storing data in ~/.codestory/public_repos/
"""

import os
import re
import shutil
import subprocess
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional

from codestory.core.logging import get_logger

LOGGER = get_logger(__name__)

# Base directory for public repos
PUBLIC_REPOS_BASE = Path.home() / ".codestory" / "public_repos"


def get_public_repos_config_path() -> Path:
    """Get path to publicRepos.yaml in project root."""
    return Path(__file__).parent.parent.parent.parent / "publicRepos.yaml"


def ensure_public_repos_base() -> Path:
    """Ensure the public repos base directory exists."""
    PUBLIC_REPOS_BASE.mkdir(parents=True, exist_ok=True)
    return PUBLIC_REPOS_BASE


def load_public_repos() -> List[Dict[str, Any]]:
    """Load public repos from config file."""
    config_path = get_public_repos_config_path()
    if not config_path.exists():
        return []
    
    with open(config_path, 'r') as f:
        data = yaml.safe_load(f) or {}
    return data.get('repos', [])


def save_public_repos(repos: List[Dict[str, Any]]) -> None:
    """Save public repos to config file."""
    config_path = get_public_repos_config_path()
    with open(config_path, 'w') as f:
        yaml.dump({'repos': repos}, f, default_flow_style=False)


def parse_github_url(url: str) -> Optional[Dict[str, str]]:
    """
    Parse GitHub URL to extract owner and repo.
    
    Accepts:
    - https://github.com/owner/repo
    - github.com/owner/repo
    - owner/repo
    
    Returns:
        Dict with 'owner', 'repo', 'slug' (owner-repo format)
    """
    # Remove trailing slashes and .git suffix
    url = url.rstrip('/').replace('.git', '')
    
    # Match github.com/owner/repo or owner/repo
    patterns = [
        r'https?://github\.com/([^/]+)/([^/]+)',
        r'github\.com/([^/]+)/([^/]+)',
        r'^([^/]+)/([^/]+)$',
    ]
    
    for pattern in patterns:
        match = re.match(pattern, url)
        if match:
            owner, repo = match.groups()
            return {
                'owner': owner,
                'repo': repo,
                'slug': f"{owner}-{repo}",
                'url': f"https://github.com/{owner}/{repo}"
            }
    
    return None


def get_repo_dir(slug: str) -> Path:
    """Get the directory for a public repo."""
    return ensure_public_repos_base() / slug


def get_repo_db_path(slug: str) -> Path:
    """Get the SQLite DB path for a public repo."""
    return get_repo_dir(slug) / "codestory.db"


def get_repo_haikus_dir(slug: str) -> Path:
    """Get the haikus directory for a public repo."""
    haikus_dir = get_repo_dir(slug) / "haikus"
    haikus_dir.mkdir(parents=True, exist_ok=True)
    return haikus_dir


def get_repo_git_dir(slug: str) -> Path:
    """Get the git clone directory for a public repo."""
    return get_repo_dir(slug) / "git"


def clone_repo(url: str, slug: str) -> bool:
    """
    Clone a GitHub public repo.
    
    Args:
        url: GitHub repo URL
        slug: owner-repo slug
        
    Returns:
        True if successful, False otherwise
    """
    git_dir = get_repo_git_dir(slug)
    
    if git_dir.exists():
        LOGGER.info(f"Repo {slug} already cloned, fetching updates...")
        return fetch_repo(slug)
    
    git_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        result = subprocess.run(
            ["git", "clone", "--bare", url, str(git_dir)],
            capture_output=True,
            text=True,
            check=True,
        )
        LOGGER.info(f"Cloned {url} to {git_dir}")
        return True
    except subprocess.CalledProcessError as exc:
        LOGGER.error(f"Failed to clone {url}: {exc.stderr}")
        return False


def fetch_repo(slug: str) -> bool:
    """
    Fetch updates for an existing repo clone.
    
    Args:
        slug: owner-repo slug
        
    Returns:
        True if successful, False otherwise
    """
    git_dir = get_repo_git_dir(slug)
    
    if not git_dir.exists():
        LOGGER.error(f"Repo {slug} not found, cannot fetch")
        return False
    
    try:
        # For bare repos, use git fetch --all
        result = subprocess.run(
            ["git", "-C", str(git_dir), "fetch", "--all"],
            capture_output=True,
            text=True,
        )
        # Fetch always returns 0 even if nothing to fetch
        LOGGER.info(f"Fetched updates for {slug}")
        return True
    except Exception as exc:
        LOGGER.error(f"Failed to fetch {slug}: {exc}")
        return False


def add_public_repo(url: str, tags: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    Add a public repo to tracking.
    
    Args:
        url: GitHub repo URL
        tags: Optional list of tags
        
    Returns:
        The added repo dict
    """
    parsed = parse_github_url(url)
    if not parsed:
        raise ValueError(f"Invalid GitHub URL: {url}")
    
    slug = parsed['slug']
    
    # Check if already exists
    repos = load_public_repos()
    for repo in repos:
        if repo.get('slug') == slug:
            LOGGER.warning(f"Repo {slug} already tracked")
            return repo
    
    # Clone the repo
    if not clone_repo(url, slug):
        raise RuntimeError(f"Failed to clone {url}")
    
    # Create repo config
    repo_config = {
        'url': parsed['url'],
        'owner': parsed['owner'],
        'repo': parsed['repo'],
        'slug': slug,
        'tags': tags or [],
        'status': 'ready',
        'added_at': str(Path(__file__).stat().st_mtime),  # Placeholder
    }
    
    repos.append(repo_config)
    save_public_repos(repos)
    
    LOGGER.info(f"Added public repo: {slug}")
    return repo_config


def remove_public_repo(slug: str) -> bool:
    """
    Remove a public repo from tracking.
    
    Args:
        slug: owner-repo slug
        
    Returns:
        True if removed, False if not found
    """
    repos = load_public_repos()
    repos = [r for r in repos if r.get('slug') != slug]
    
    if len(repos) == load_public_repos():
        return False  # Not found
    
    save_public_repos(repos)
    
    # Optionally delete the data
    # repo_dir = get_repo_dir(slug)
    # if repo_dir.exists():
    #     shutil.rmtree(repo_dir)
    
    LOGGER.info(f"Removed public repo: {slug}")
    return True


def get_public_repo(slug: str) -> Optional[Dict[str, Any]]:
    """Get a specific public repo config."""
    repos = load_public_repos()
    for repo in repos:
        if repo.get('slug') == slug:
            return repo
    return None


def list_public_repos() -> List[Dict[str, Any]]:
    """List all tracked public repos."""
    return load_public_repos()
