"""Bounded, read-only views of a staged snapshot copy. Repository text is data, never instruction."""
from pathlib import Path

MAX_FILE_BYTES = 262144
SKIP = {"node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
TEXT = {".py", ".md", ".txt", ".toml", ".cfg", ".ini", ".json", ".yaml", ".yml", ".sh", ""}


class SnapshotTools:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, value):
        if not isinstance(value, str) or len(value) > 400 or "\x00" in value:
            raise ValueError("Path must be a short relative path.")
        target = (self.root / value).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError("Path is outside the repository.")
        return target

    def list_files(self, path="."):
        target = self.path(path)
        if not target.is_dir():
            raise ValueError("Not a directory.")
        entries = []
        for item in sorted(target.iterdir())[:300]:
            relative = str(item.relative_to(self.root))
            entries.append(relative + "/" if item.is_dir() else f"{relative} ({item.stat().st_size} bytes)")
        return {"entries": entries, "truncated": len(entries) == 300}

    def read_file(self, path, start_line=1, max_lines=120):
        target = self.path(path)
        if not target.is_file():
            raise ValueError("Not a file.")
        if target.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("File is larger than 256 KiB; search it instead.")
        if type(start_line) is not int or type(max_lines) is not int or start_line < 1 or not 1 <= max_lines <= 200:
            raise ValueError("start_line must be >= 1 and max_lines between 1 and 200.")
        try:
            lines = target.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            raise ValueError("File is not UTF-8 text.") from None
        chosen = lines[start_line - 1:start_line - 1 + max_lines]
        return {"path": path, "total_lines": len(lines),
                "lines": [f"{start_line + index}: {line[:240]}" for index, line in enumerate(chosen)]}

    def search_code(self, query, path="."):
        if not isinstance(query, str) or not 2 <= len(query) <= 120:
            raise ValueError("Query must be 2-120 characters of literal text.")
        target, needle, matches, scanned = self.path(path), query.lower(), [], 0
        files = [target] if target.is_file() else sorted(target.rglob("*"))
        for item in files:
            if len(matches) >= 40 or scanned >= 1500:
                break
            if (not item.is_file() or item.suffix not in TEXT or item.stat().st_size > MAX_FILE_BYTES
                    or SKIP.intersection(item.relative_to(self.root).parts)):
                continue
            scanned += 1
            try:
                text = item.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for number, line in enumerate(text.splitlines(), 1):
                if needle in line.lower():
                    matches.append(f"{item.relative_to(self.root)}:{number}: {line.strip()[:200]}")
                    if len(matches) >= 40:
                        break
        return {"matches": matches, "truncated": len(matches) >= 40}
