#!/usr/bin/env python3
"""
sync_content.py — Sync wiki markdown files into Starlight content directory.

Usage:
    python scripts/sync_content.py [--dry-run] [--verbose]

What it does:
  - Reads all .md files from agent-cli/docs/wiki/ and subdirectories
  - Copies them into src/content/docs/ with matching directory structure
  - Adds Starlight frontmatter (title, description) if missing
  - Fixes internal wiki links to work with Starlight routing
  - Reports which files were added/updated/skipped

Notes:
  - Does NOT overwrite manually-created pages in src/content/docs/
    (getting-started/, architecture/ hand-crafted pages are protected)
  - Only syncs files from the wiki that don't already exist as hand-crafted pages
  - Run from the web/docs/ directory
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

# Directories relative to this script's location (web/docs/)
SCRIPT_DIR = Path(__file__).parent
DOCS_DIR = SCRIPT_DIR.parent  # web/docs/
REPO_ROOT = DOCS_DIR.parent.parent.parent  # HyperLiquid_Bot/
WIKI_SOURCE = REPO_ROOT / "agent-cli" / "docs" / "wiki"
CONTENT_DEST = DOCS_DIR / "src" / "content" / "docs"

# Wiki subdirectory → Starlight section mapping
SECTION_MAP = {
    "architecture": "architecture",
    "components": "components",
    "trading": "trading",
    "operations": "operations",
    "decisions": "decisions",
    "workflows": "workflows",
    "": "reference",  # root-level files go to reference/
}

# Hand-crafted pages that should NOT be overwritten by sync
# Add any page you've manually written and don't want clobbered
PROTECTED_FILES = {
    "index.mdx",
    "getting-started/overview.md",
    "getting-started/installation.md",
    "getting-started/quick-start.md",
    "architecture/overview.md",
    "architecture/data-flow.md",
    "architecture/tiers.md",
    "components/daemon.md",
    "components/telegram-bot.md",
    "components/ai-agent.md",
    "components/conviction-engine.md",
    "components/heartbeat.md",
    "trading/markets.md",
    "trading/oil-knowledge.md",
    "trading/sizing-rules.md",
    "trading/portfolio-strategy.md",
    "operations/runbook.md",
    "operations/security.md",
    "operations/tiers.md",
}

# Files in wiki to skip (internal-only, not useful as public docs)
SKIP_FILES = {
    "MAINTAINING.md",
    "build-log.md",  # internal dev history, skip for public docs
}


def extract_title_from_content(content: str, filename: str) -> str:
    """Extract title from first H1 heading, or derive from filename."""
    match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
    if match:
        return match.group(1).strip()
    # Derive from filename: decisions/001-foo.md → "001: Foo"
    stem = Path(filename).stem
    stem = re.sub(r'^(\d+)-', r'\1: ', stem)
    return stem.replace('-', ' ').title()


def extract_description(content: str) -> str:
    """Extract first meaningful paragraph as description."""
    # Skip frontmatter
    body = content
    if content.startswith('---'):
        end = content.find('---', 3)
        if end != -1:
            body = content[end + 3:].strip()

    # Skip headings, find first paragraph
    lines = body.split('\n')
    paragraph_lines = []
    in_paragraph = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            if in_paragraph:
                break
            continue
        if stripped.startswith('#') or stripped.startswith('|') or stripped.startswith('```'):
            if in_paragraph:
                break
            continue
        in_paragraph = True
        paragraph_lines.append(stripped)
        if len(' '.join(paragraph_lines)) > 160:
            break

    desc = ' '.join(paragraph_lines)
    # Truncate at sentence boundary if possible
    if len(desc) > 160:
        idx = desc.rfind('.', 0, 160)
        if idx > 60:
            desc = desc[:idx + 1]
        else:
            desc = desc[:157] + '...'
    return desc


def has_frontmatter(content: str) -> bool:
    """Check if content already has YAML frontmatter."""
    return content.startswith('---\n') or content.startswith('---\r\n')


def add_frontmatter(content: str, filename: str) -> str:
    """Add Starlight frontmatter to content if missing."""
    if has_frontmatter(content):
        return content

    title = extract_title_from_content(content, filename)
    description = extract_description(content)

    # Clean description for YAML (escape quotes)
    description = description.replace('"', '\\"').replace('\n', ' ')

    frontmatter = f'---\ntitle: "{title}"\ndescription: "{description}"\n---\n\n'
    return frontmatter + content


def fix_wiki_links(content: str, source_section: str) -> str:
    """
    Fix internal wiki links to work with Starlight routing.

    Wiki links like: [foo](../components/bar.md)
    Become Starlight links: [foo](/components/bar/)

    Wiki links like: [foo](bar.md)
    Become: [foo](/section/bar/) (using source_section for context)
    """
    def replace_link(match):
        text = match.group(1)
        href = match.group(2)

        # Skip external links and anchors
        if href.startswith('http') or href.startswith('#'):
            return match.group(0)

        # Remove .md extension
        href_no_ext = re.sub(r'\.md$', '', href)

        # Handle relative paths
        if href_no_ext.startswith('../'):
            # Navigate up from current section
            href_no_ext = href_no_ext[3:]  # remove ../
        elif not href_no_ext.startswith('/') and '/' not in href_no_ext:
            # Same-directory link — prepend section
            if source_section:
                href_no_ext = f"{source_section}/{href_no_ext}"

        # Normalize to absolute path
        if not href_no_ext.startswith('/'):
            href_no_ext = '/' + href_no_ext

        # Ensure trailing slash for Starlight
        if not href_no_ext.endswith('/'):
            href_no_ext = href_no_ext + '/'

        return f'[{text}]({href_no_ext})'

    # Match markdown links [text](href)
    content = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', replace_link, content)
    return content


def sync_file(source: Path, dest: Path, section: str, dry_run: bool, verbose: bool) -> str:
    """Sync a single wiki file to Starlight content dir. Returns status."""

    # Check if protected
    rel_dest = dest.relative_to(CONTENT_DEST)
    if str(rel_dest) in PROTECTED_FILES:
        if verbose:
            print(f"  [SKIP protected] {rel_dest}")
        return "protected"

    content = source.read_text(encoding='utf-8')

    # Add frontmatter if missing
    content = add_frontmatter(content, source.name)

    # Fix internal links
    content = fix_wiki_links(content, section)

    if dest.exists():
        existing = dest.read_text(encoding='utf-8')
        if existing == content:
            if verbose:
                print(f"  [UNCHANGED] {rel_dest}")
            return "unchanged"
        status = "updated"
    else:
        status = "added"

    if not dry_run:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding='utf-8')

    print(f"  [{status.upper()}] {rel_dest}")
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without writing files')
    parser.add_argument('--verbose', action='store_true', help='Show unchanged files too')
    args = parser.parse_args()

    if not WIKI_SOURCE.exists():
        print(f"ERROR: Wiki source not found: {WIKI_SOURCE}", file=sys.stderr)
        sys.exit(1)

    if not CONTENT_DEST.exists():
        print(f"ERROR: Content destination not found: {CONTENT_DEST}", file=sys.stderr)
        sys.exit(1)

    print(f"Syncing: {WIKI_SOURCE}")
    print(f"     to: {CONTENT_DEST}")
    if args.dry_run:
        print("(DRY RUN — no files will be written)")
    print()

    counts = {"added": 0, "updated": 0, "unchanged": 0, "protected": 0, "skipped": 0}

    for source_file in sorted(WIKI_SOURCE.rglob("*.md")):
        # Determine relative path within wiki
        rel_path = source_file.relative_to(WIKI_SOURCE)

        # Skip internal files
        if source_file.name in SKIP_FILES:
            if args.verbose:
                print(f"  [SKIP internal] {rel_path}")
            counts["skipped"] += 1
            continue

        # Determine section from parent directory
        parts = rel_path.parts
        if len(parts) == 1:
            # Root-level file
            section = ""
            dest_subdir = CONTENT_DEST / "reference"
        else:
            section = parts[0]
            dest_subdir = CONTENT_DEST / SECTION_MAP.get(section, section)

        dest_file = dest_subdir / rel_path.name

        status = sync_file(source_file, dest_file, section, args.dry_run, args.verbose)
        counts[status] = counts.get(status, 0) + 1

    print()
    print(f"Done. Added: {counts['added']}, Updated: {counts['updated']}, "
          f"Unchanged: {counts['unchanged']}, Protected: {counts['protected']}, "
          f"Skipped: {counts['skipped']}")

    if args.dry_run:
        print("(DRY RUN — no files were written)")


if __name__ == "__main__":
    main()
