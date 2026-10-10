import gzip
from pathlib import PurePosixPath
import tarfile

from .client import GitHubFailure


class BoundedReader:
    def __init__(self, source, limit, check_active):
        self.source, self.limit, self.check_active = source, limit, check_active
        self.count = 0

    def read(self, size=-1):
        self.check_active()
        data = self.source.read(min(size if size >= 0 else 65536, 65536))
        self.count += len(data)
        if self.count > self.limit:
            raise GitHubFailure("extracted_limit", "Expanded archive exceeds the extraction size limit.", 413)
        return data


def extract_archive(archive_path, destination, settings, check_active) -> dict:
    destination.mkdir(mode=0o700)
    total, count, files, root = 0, 0, 0, None
    seen = set()
    warnings = set()
    # Count decompressed headers and padding too, including oversized PAX metadata.
    expanded_limit = settings.import_extracted_bytes + settings.import_file_count * 2048 + 1024 * 1024
    try:
        with gzip.open(archive_path, "rb") as compressed:
            reader = BoundedReader(compressed, expanded_limit, check_active)
            with tarfile.open(fileobj=reader, mode="r|") as archive:
                for member in archive:
                    check_active()
                    count += 1
                    if count > settings.import_file_count:
                        raise GitHubFailure("file_limit", "Repository exceeds the archive entry count limit.", 413)
                    name = member.name
                    parts = PurePosixPath(name).parts
                    if (not parts or len(parts) > 64 or len(name.encode()) > 4096
                        or name.startswith("/") or "\\" in name or "\x00" in name
                        or any(not part or part in {".", ".."} for part in name.rstrip("/").split("/"))):
                        raise GitHubFailure("unsafe_archive", "Archive contains an unsafe path.")
                    root = root or parts[0]
                    if parts[0] != root:
                        raise GitHubFailure("unsafe_archive", "Archive has multiple source roots.")
                    if not member.isdir() and not member.isfile():
                        # Reject all links and special files instead of interpreting attacker-controlled targets.
                        raise GitHubFailure("unsafe_archive", "Archive contains a symlink, hard link, or special file.")
                    if len(parts) == 1:
                        if not member.isdir():
                            raise GitHubFailure("unsafe_archive", "Archive root must be a directory.")
                        continue
                    relative = PurePosixPath(*parts[1:])
                    if relative in seen or relative.parts[0] == ".git":
                        raise GitHubFailure("unsafe_archive", "Archive contains duplicate paths or Git metadata.")
                    seen.add(relative)
                    target = destination.joinpath(*relative.parts)
                    if not target.resolve().is_relative_to(destination.resolve()):
                        raise GitHubFailure("unsafe_archive", "Archive path escapes the source workspace.")
                    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                    if member.isdir():
                        target.mkdir(exist_ok=True, mode=0o700)
                        continue
                    if member.size < 0:
                        raise GitHubFailure("unsafe_archive", "Archive contains an invalid file size.")
                    total += member.size
                    files += 1
                    if total > settings.import_extracted_bytes:
                        raise GitHubFailure("extracted_limit", "Repository exceeds the extracted size limit.", 413)
                    source = archive.extractfile(member)
                    prefix = bytearray()
                    with target.open("xb") as output:
                        target.chmod(0o600)
                        remaining = member.size
                        while remaining:
                            check_active()
                            chunk = source.read(min(remaining, 65536))
                            if not chunk:
                                raise GitHubFailure("invalid_archive", "Archive file was truncated.")
                            if len(prefix) < 1024:
                                prefix.extend(chunk[:1024 - len(prefix)])
                            output.write(chunk)
                            remaining -= len(chunk)
                    if relative.name == ".gitmodules":
                        warnings.add("submodules_not_imported")
                    if prefix.startswith(b"version https://git-lfs.github.com/spec/v1"):
                        warnings.add("git_lfs_objects_not_imported")
                    if relative.name == ".gitattributes":
                        with target.open("rb") as attributes:
                            previous = b""
                            while chunk := attributes.read(65536):
                                check_active()
                                if b"filter=lfs" in previous + chunk:
                                    warnings.add("git_lfs_objects_not_imported")
                                    break
                                previous = chunk[-16:]
        if root is None:
            raise GitHubFailure("empty_repository", "Repository archive is empty.", 409)
        return {"file_count": files,
                "extracted_bytes": total, "warnings": sorted(warnings)}
    except (tarfile.TarError, EOFError, gzip.BadGzipFile):
        raise GitHubFailure("invalid_archive", "GitHub archive is invalid or truncated.") from None
