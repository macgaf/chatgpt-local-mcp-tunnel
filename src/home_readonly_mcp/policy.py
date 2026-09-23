from __future__ import annotations

import fnmatch
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


DEFAULT_DENY = [
    ".ssh",
    ".ssh/**",
    ".gnupg",
    ".gnupg/**",
    ".aws",
    ".aws/**",
    ".azure",
    ".azure/**",
    ".kube",
    ".kube/**",
    ".docker/config.json",
    ".git-credentials",
    ".netrc",
    ".npmrc",
    ".pypirc",
    "Library/Keychains",
    "Library/Keychains/**",
    "Library/**/Cookies*",
    "Library/**/Login Data*",
    ".env",
    "**/.env",
    ".env.*",
    "**/.env.*",
    "*.pem",
    "**/*.pem",
    "*.key",
    "**/*.key",
    "*.p12",
    "**/*.p12",
    "*.pfx",
    "**/*.pfx",
    "credentials*",
    "**/credentials*",
    "secrets",
    "secrets/**",
    "**/secrets",
    "**/secrets/**",
]

DEFAULT_FORCE_ALLOW = [
    ".env.example",
    "**/.env.example",
    ".env.sample",
    "**/.env.sample",
    ".env.template",
    "**/.env.template",
]

DEFAULT_NOISY_DENY = [
    ".Trash",
    ".Trash/**",
    "Library/Caches",
    "Library/Caches/**",
    "node_modules/**",
    "**/node_modules/**",
    ".venv/**",
    "**/.venv/**",
    "__pycache__/**",
    "**/__pycache__/**",
]


class PolicyError(PermissionError):
    pass


@dataclass(frozen=True)
class AccessDecision:
    allowed: bool
    reason: str
    relative_path: str
    resolved_path: Path


@dataclass
class Policy:
    root: Path
    default_policy: str = "allow"
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=lambda: list(DEFAULT_DENY + DEFAULT_NOISY_DENY))
    force_allow: list[str] = field(default_factory=lambda: list(DEFAULT_FORCE_ALLOW))
    max_file_size: int = 8 * 1024 * 1024
    max_text_output_bytes: int = 512 * 1024
    max_directory_entries: int = 500
    max_search_files: int = 5000
    max_search_results: int = 200
    binary_policy: str = "metadata_only"

    @classmethod
    def from_file(cls, path: str | os.PathLike[str] | None = None) -> "Policy":
        config_path = Path(path or os.environ.get("HOME_READONLY_MCP_CONFIG", "~/.config/home-readonly-mcp/config.json")).expanduser()
        if not config_path.exists():
            return cls(root=Path.home().resolve())
        data = json.loads(config_path.read_text(encoding="utf-8"))
        root = Path(data.get("root", "~")).expanduser().resolve()
        return cls(
            root=root,
            default_policy=data.get("default_policy", "allow"),
            allow=list(data.get("allow", [])),
            deny=list(data.get("deny", DEFAULT_DENY + DEFAULT_NOISY_DENY)),
            force_allow=list(data.get("force_allow", DEFAULT_FORCE_ALLOW)),
            max_file_size=int(data.get("max_file_size", 8 * 1024 * 1024)),
            max_text_output_bytes=int(data.get("max_text_output_bytes", 512 * 1024)),
            max_directory_entries=int(data.get("max_directory_entries", 500)),
            max_search_files=int(data.get("max_search_files", 5000)),
            max_search_results=int(data.get("max_search_results", 200)),
            binary_policy=data.get("binary_policy", "metadata_only"),
        )

    def _relative(self, resolved: Path) -> str:
        try:
            rel = resolved.relative_to(self.root)
        except ValueError as exc:
            raise PolicyError("Path resolves outside HOME root") from exc
        s = rel.as_posix()
        return "." if s == "." else s

    @staticmethod
    def _matches(rel: str, patterns: Iterable[str]) -> bool:
        if rel == ".":
            candidates = ["."]
        else:
            candidates = [rel, f"/{rel}"]
        for raw in patterns:
            pattern = os.path.expanduser(str(raw)).replace("\\", "/")
            # Absolute/~/ patterns are normalized by the caller against HOME only when possible.
            if pattern.startswith("~/"):
                pattern = pattern[2:]
            base_pattern = pattern[:-3] if pattern.endswith("/**") else None
            for candidate in candidates:
                normalized_candidate = candidate[1:] if candidate.startswith("/") else candidate
                if base_pattern is not None and normalized_candidate == base_pattern:
                    return True
                if fnmatch.fnmatchcase(candidate, pattern):
                    return True
        return False

    def resolve(self, user_path: str | os.PathLike[str]) -> AccessDecision:
        raw = str(user_path or ".").strip()
        if raw.startswith("~"):
            candidate = Path(raw).expanduser()
        elif Path(raw).is_absolute():
            candidate = Path(raw)
        else:
            candidate = self.root / raw

        # resolve() follows symlinks; strict=False still resolves existing symlink components.
        resolved = candidate.resolve(strict=False)
        rel = self._relative(resolved)

        if self._matches(rel, self.force_allow):
            return AccessDecision(True, "force_allow", rel, resolved)
        if self._matches(rel, self.deny):
            return AccessDecision(False, "deny", rel, resolved)
        if self.allow and self._matches(rel, self.allow):
            return AccessDecision(True, "allow", rel, resolved)
        if self.default_policy == "deny":
            return AccessDecision(False, "default_deny", rel, resolved)
        return AccessDecision(True, "default_allow", rel, resolved)

    def require(self, user_path: str | os.PathLike[str], *, must_exist: bool = True) -> Path:
        decision = self.resolve(user_path)
        if not decision.allowed:
            raise PolicyError(f"Access denied by policy: {decision.relative_path} ({decision.reason})")
        if must_exist and not decision.resolved_path.exists():
            raise FileNotFoundError(decision.relative_path)
        return decision.resolved_path

    def relative(self, path: Path) -> str:
        return self._relative(path.resolve(strict=False))
