from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from .policy import Policy, PolicyError


def _is_probably_binary(path: Path, sample_size: int = 8192) -> bool:
    with path.open("rb") as f:
        sample = f.read(sample_size)
    if b"\x00" in sample:
        return True
    if not sample:
        return False
    textish = sum(1 for b in sample if b in b"\t\n\r\f\b" or 32 <= b <= 126 or b >= 128)
    return textish / len(sample) < 0.75


class ReadOnlyHomeService:
    def __init__(self, policy: Policy):
        self.policy = policy

    def policy_info(self) -> dict[str, Any]:
        return {
            "root": str(self.policy.root),
            "mode": "read_only",
            "default_policy": self.policy.default_policy,
            "allow": self.policy.allow,
            "deny": self.policy.deny,
            "force_allow": self.policy.force_allow,
            "max_file_size": self.policy.max_file_size,
            "max_text_output_bytes": self.policy.max_text_output_bytes,
            "binary_policy": self.policy.binary_policy,
        }

    def file_info(self, path: str) -> dict[str, Any]:
        p = self.policy.require(path)
        st = p.stat()
        kind = "directory" if p.is_dir() else "file" if p.is_file() else "other"
        info: dict[str, Any] = {
            "path": self.policy.relative(p),
            "absolute_path": str(p),
            "type": kind,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "mode": stat.filemode(st.st_mode),
            "is_symlink": Path(path).expanduser().is_symlink() if Path(path).is_absolute() else (self.policy.root / path).is_symlink(),
        }
        if p.is_file() and st.st_size <= self.policy.max_file_size:
            info["binary"] = _is_probably_binary(p)
            h = hashlib.sha256()
            with p.open("rb") as f:
                for chunk in iter(lambda: f.read(1024 * 1024), b""):
                    h.update(chunk)
            info["sha256"] = h.hexdigest()
        return info

    def list_directory(self, path: str = ".", limit: int | None = None) -> dict[str, Any]:
        p = self.policy.require(path)
        if not p.is_dir():
            raise NotADirectoryError(self.policy.relative(p))
        cap = min(limit or self.policy.max_directory_entries, self.policy.max_directory_entries)
        entries: list[dict[str, Any]] = []
        hidden_by_policy = 0
        with os.scandir(p) as it:
            for entry in sorted(it, key=lambda e: e.name.lower()):
                child = p / entry.name
                try:
                    decision = self.policy.resolve(child)
                except PolicyError:
                    hidden_by_policy += 1
                    continue
                if not decision.allowed:
                    hidden_by_policy += 1
                    continue
                try:
                    st = entry.stat(follow_symlinks=True)
                    if entry.is_dir(follow_symlinks=True):
                        typ = "directory"
                    elif entry.is_file(follow_symlinks=True):
                        typ = "file"
                    else:
                        typ = "other"
                    entries.append({
                        "name": entry.name,
                        "path": decision.relative_path,
                        "type": typ,
                        "size": st.st_size,
                        "mtime_ns": st.st_mtime_ns,
                        "symlink": entry.is_symlink(),
                    })
                except (OSError, PolicyError):
                    continue
                if len(entries) >= cap:
                    break
        return {
            "path": self.policy.relative(p),
            "entries": entries,
            "returned": len(entries),
            "limit": cap,
            "hidden_by_policy": hidden_by_policy,
            "truncated": len(entries) >= cap,
        }

    def read_file(self, path: str, start_line: int = 1, end_line: int | None = None) -> dict[str, Any]:
        p = self.policy.require(path)
        if not p.is_file():
            raise IsADirectoryError(self.policy.relative(p))
        size = p.stat().st_size
        if size > self.policy.max_file_size:
            raise ValueError(f"File exceeds max_file_size ({size} > {self.policy.max_file_size})")
        if _is_probably_binary(p):
            raise ValueError("Binary file content is not exposed; use file_info for metadata")
        start = max(1, int(start_line))
        end = int(end_line) if end_line is not None else None
        if end is not None and end < start:
            raise ValueError("end_line must be >= start_line")

        out: list[str] = []
        out_bytes = 0
        last_line = start - 1
        truncated = False
        with p.open("r", encoding="utf-8", errors="replace") as f:
            for lineno, line in enumerate(f, start=1):
                if lineno < start:
                    continue
                if end is not None and lineno > end:
                    break
                encoded_len = len(line.encode("utf-8", errors="replace"))
                if out_bytes + encoded_len > self.policy.max_text_output_bytes:
                    truncated = True
                    break
                out.append(line)
                out_bytes += encoded_len
                last_line = lineno
        return {
            "path": self.policy.relative(p),
            "start_line": start,
            "end_line": last_line,
            "truncated": truncated,
            "content": "".join(out),
        }

    def find_files(self, pattern: str, path: str = ".", max_results: int = 100) -> dict[str, Any]:
        base = self.policy.require(path)
        if not base.is_dir():
            raise NotADirectoryError(self.policy.relative(base))
        cap = max(1, min(int(max_results), self.policy.max_search_results))
        results: list[str] = []
        visited = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            root_path = Path(root)
            kept_dirs = []
            for d in dirs:
                try:
                    decision = self.policy.resolve(root_path / d)
                except PolicyError:
                    continue
                if decision.allowed:
                    kept_dirs.append(d)
            dirs[:] = kept_dirs
            for name in files:
                if visited >= self.policy.max_search_files:
                    return {"results": results, "truncated": True, "reason": "max_search_files"}
                visited += 1
                p = root_path / name
                try:
                    decision = self.policy.resolve(p)
                except PolicyError:
                    continue
                if not decision.allowed:
                    continue
                rel_from_base = p.relative_to(base).as_posix()
                if Path(rel_from_base).match(pattern) or Path(name).match(pattern):
                    results.append(decision.relative_path)
                    if len(results) >= cap:
                        return {"results": results, "truncated": True, "reason": "max_results"}
        return {"results": results, "truncated": False, "visited_files": visited}

    def search_text(
        self,
        query: str,
        path: str = ".",
        glob: str = "*",
        max_results: int = 100,
        case_sensitive: bool = False,
    ) -> dict[str, Any]:
        if not query:
            raise ValueError("query must not be empty")
        base = self.policy.require(path)
        if not base.is_dir():
            raise NotADirectoryError(self.policy.relative(base))
        cap = max(1, min(int(max_results), self.policy.max_search_results))
        needle = query if case_sensitive else query.casefold()
        results: list[dict[str, Any]] = []
        visited = 0
        skipped_binary = 0
        skipped_large = 0
        for root, dirs, files in os.walk(base, followlinks=False):
            root_path = Path(root)
            kept_dirs = []
            for d in dirs:
                try:
                    decision = self.policy.resolve(root_path / d)
                except PolicyError:
                    continue
                if decision.allowed:
                    kept_dirs.append(d)
            dirs[:] = kept_dirs
            for name in files:
                if visited >= self.policy.max_search_files:
                    return {
                        "results": results,
                        "truncated": True,
                        "reason": "max_search_files",
                        "visited_files": visited,
                        "skipped_binary": skipped_binary,
                        "skipped_large": skipped_large,
                    }
                visited += 1
                p = root_path / name
                try:
                    decision = self.policy.resolve(p)
                except PolicyError:
                    continue
                if not decision.allowed:
                    continue
                rel_from_base = p.relative_to(base).as_posix()
                if not (Path(rel_from_base).match(glob) or Path(name).match(glob)):
                    continue
                try:
                    if p.stat().st_size > self.policy.max_file_size:
                        skipped_large += 1
                        continue
                    if _is_probably_binary(p):
                        skipped_binary += 1
                        continue
                    with p.open("r", encoding="utf-8", errors="replace") as f:
                        for lineno, line in enumerate(f, start=1):
                            hay = line if case_sensitive else line.casefold()
                            if needle in hay:
                                results.append({
                                    "path": decision.relative_path,
                                    "line": lineno,
                                    "text": line.rstrip("\n\r")[:2000],
                                })
                                if len(results) >= cap:
                                    return {
                                        "results": results,
                                        "truncated": True,
                                        "reason": "max_results",
                                        "visited_files": visited,
                                        "skipped_binary": skipped_binary,
                                        "skipped_large": skipped_large,
                                    }
                except (OSError, UnicodeError):
                    continue
        return {
            "results": results,
            "truncated": False,
            "visited_files": visited,
            "skipped_binary": skipped_binary,
            "skipped_large": skipped_large,
        }
