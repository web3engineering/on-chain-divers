"""Small helpers for OnchainDivers capture archives.

Data and indexer documentation: https://onchaindivers.com
"""

from __future__ import annotations

import shutil
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath


class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a":
            href = dict(attrs).get("href")
            if href:
                self.hrefs.append(href)


def is_http(source: str) -> bool:
    return urllib.parse.urlsplit(source).scheme in {"http", "https"}


def scan(source: str, suffixes: tuple[str, ...], max_depth: int = 3) -> list[str]:
    """Return safe capture names from a local directory or HTTP listing."""
    if not is_http(source):
        root = Path(source).expanduser().resolve()
        if not root.is_dir():
            raise ValueError("capture source is not a directory")
        return sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path.name.endswith(suffixes)
        )

    base = source.rstrip("/") + "/"
    origin = urllib.parse.urlsplit(base)
    base_path = origin.path.rstrip("/") + "/"
    pending = [(base, 0)]
    visited: set[str] = set()
    names: list[str] = []
    while pending:
        listing_url, depth = pending.pop(0)
        if listing_url in visited:
            continue
        visited.add(listing_url)
        request = urllib.request.Request(
            listing_url, headers={"User-Agent": "onchaindivers-examples/1"}
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            body = response.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise ValueError("archive listing exceeds 16 MiB")
        parser = _Links()
        parser.feed(body.decode("utf-8", errors="replace"))
        for href in parser.hrefs:
            absolute = urllib.parse.urljoin(listing_url, href)
            resolved = urllib.parse.urlsplit(absolute)
            if resolved.scheme != origin.scheme or resolved.netloc != origin.netloc:
                continue
            decoded_path = urllib.parse.unquote(resolved.path)
            if not decoded_path.startswith(base_path):
                continue
            relative = decoded_path[len(base_path):].strip("/")
            parts = PurePosixPath(relative).parts
            if not relative or any(part in {"", ".", ".."} for part in parts):
                continue
            if href.endswith("/"):
                if depth < max_depth:
                    pending.append((absolute.rstrip("/") + "/", depth + 1))
            elif relative.endswith(suffixes):
                names.append(relative)
    return sorted(set(names))


def download(source: str, name: str, destination: Path, max_bytes: int = 64 * 1024 * 1024) -> Path:
    """Copy one named capture, rejecting traversal and unexpectedly large files."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("capture name must be a safe relative path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not is_http(source):
        root = Path(source).expanduser().resolve()
        candidate = (root / name).resolve()
        candidate.relative_to(root)
        if candidate.stat().st_size > max_bytes:
            raise ValueError("capture exceeds configured download limit")
        shutil.copyfile(candidate, destination)
        return destination

    encoded = "/".join(urllib.parse.quote(part) for part in relative.parts)
    url = urllib.parse.urljoin(source.rstrip("/") + "/", encoded)
    request = urllib.request.Request(url, headers={"User-Agent": "onchaindivers-examples/1"})
    written = 0
    with urllib.request.urlopen(request, timeout=30) as response, destination.open("wb") as target:
        declared = response.headers.get("Content-Length")
        if declared and int(declared) > max_bytes:
            raise ValueError("capture exceeds configured download limit")
        while chunk := response.read(1024 * 1024):
            written += len(chunk)
            if written > max_bytes:
                raise ValueError("capture exceeds configured download limit")
            target.write(chunk)
    return destination


def content_length(source: str, name: str) -> int:
    """Return a local or remote capture size without downloading its body."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise ValueError("capture name must be a safe relative path")
    if not is_http(source):
        root = Path(source).expanduser().resolve()
        candidate = (root / relative).resolve()
        candidate.relative_to(root)
        return candidate.stat().st_size
    encoded = "/".join(urllib.parse.quote(part) for part in relative.parts)
    url = urllib.parse.urljoin(source.rstrip("/") + "/", encoded)
    request = urllib.request.Request(
        url,
        method="HEAD",
        headers={"User-Agent": "onchaindivers-examples/1"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        value = response.headers.get("Content-Length")
    if value is None:
        raise ValueError("capture server did not provide Content-Length")
    return int(value)
