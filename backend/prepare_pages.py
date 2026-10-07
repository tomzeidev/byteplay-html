"""Build a public-only artifact; backend code, credentials, and databases stay out."""
import argparse
import shutil
from pathlib import Path

WEB_SUFFIXES = {'.html', '.css', '.js', '.svg', '.png', '.jpg', '.jpeg', '.webp', '.gif', '.ico', '.json'}


def prepare(destination, root=None):
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    destination = Path(destination).resolve()
    if destination == root.resolve() or destination in root.resolve().parents:
        raise ValueError('The destination must be a separate directory.')
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('Use an empty output directory to prevent stale public files.')
    for source in root.iterdir():
        if source.is_file() and not source.name.startswith('.') and source.suffix.lower() in WEB_SUFFIXES:
            shutil.copy2(source, destination / source.name)
    for directory in ['img', 'posts']:
        for source in (root / directory).rglob('*'):
            if source.is_file() and source.suffix.lower() in WEB_SUFFIXES:
                target = destination / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination')
    args = parser.parse_args()
    prepare(args.destination)
