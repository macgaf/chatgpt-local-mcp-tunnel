"""Local-only security settings. No MCP tool can change these settings."""
from __future__ import annotations
from dataclasses import dataclass, field
import fnmatch
import json
import os
from pathlib import Path
import re
import tempfile
import unicodedata
from .errors import Fault

APP = 'chatgpt-local-mcp-tunnel'
CREDENTIAL_LOCATIONS = [
    '.ssh', '.gnupg', '.aws', '.azure', '.kube',
    '.codex/auth.json', '.claude/.credentials.json', '.docker/config.json',
    '.git-credentials', '.netrc', '.npmrc', '.pypirc',
    'Library/Keychains', 'Library/Cookies',
    'Library/Application Support/Google/Chrome', 'Library/Application Support/Firefox',
    'Library/Application Support/Microsoft Edge', 'Library/Safari',
    '.config/google-chrome', '.config/chromium', '.mozilla',
    '.local/share/keyrings', '.local/share/kwalletd', '.config/kwalletrc',
    'AppData/Local/Microsoft/Credentials', 'AppData/Roaming/Microsoft/Credentials',
    'AppData/Local/Microsoft/Vault', 'AppData/Roaming/Microsoft/Vault',
    'AppData/Local/Google/Chrome/User Data', 'AppData/Local/Microsoft/Edge/User Data',
]
# 默认只保留结构和缓存范围；不按文件名、扩展名或关键词猜测秘密。
DEFAULT_DENY = ['**/.git/**', '**/node_modules/**', '**/.venv/**',
                '**/__pycache__/**', '.Trash/**', 'Library/Caches/**']


def credential_paths():
    """仅保护真实用户级凭据存储位置，项目中的同名路径不属于这些位置。"""
    home = Path.home().resolve()
    result = []
    for relative in CREDENTIAL_LOCATIONS:
        path = home / relative
        for candidate in (path, path.resolve()):
            if candidate not in result:
                result.append(candidate)
    return result


def locations():
    home = Path.home()
    if os.name == 'nt':
        config = Path(os.environ.get('APPDATA', home / 'AppData/Roaming')) / APP
        app = Path(os.environ.get('LOCALAPPDATA', home / 'AppData/Local')) / APP
        state = app / 'state'
    else:
        config = Path(os.environ.get('XDG_CONFIG_HOME', home / '.config')) / APP
        app = Path(os.environ.get('XDG_DATA_HOME', home / '.local/share')) / APP
        state = Path(os.environ.get('XDG_STATE_HOME', home / '.local/state')) / APP
    return config, app, state


def matches(rel, pattern):
    """Case-insensitive policy globs; **/ also matches a root-level basename."""
    rel = rel.replace('\\', '/').casefold()
    pattern = pattern.replace('\\', '/').casefold().removeprefix('~/').lstrip('/')
    patterns = [pattern]
    if pattern.startswith('**/'):
        patterns.append(pattern[3:])
    for pat in patterns:
        if fnmatch.fnmatchcase(rel, pat):
            return True
        if pat.endswith('/**') and fnmatch.fnmatchcase(rel, pat[:-3]):
            return True
    return False


@dataclass
class Policy:
    root: Path = field(default_factory=Path.home)
    mode: str = 'read_only'
    default_policy: str = 'allow'
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=lambda: DEFAULT_DENY.copy())
    force_allow: list[str] = field(default_factory=list)
    write_roots: list[str] = field(default_factory=list)
    max_file_size: int = 32 * 1024 * 1024
    max_text_output_bytes: int = 256 * 1024
    max_directory_entries: int = 500
    max_search_files: int = 10000
    max_search_results: int = 200
    max_image_pixels: int = 80_000_000
    max_image_bytes: int = 2 * 1024 * 1024
    enable_commands: bool = False
    enable_git_push: bool = False
    enable_codex_history: bool = True
    codex_history_home: str = ''
    git_push_remotes: list[str] = field(default_factory=list)
    git_credential_helper: str = ''
    git_user_name: str = ''
    git_user_email: str = ''
    max_command_timeout: int = 3600
    max_command_output_bytes: int = 1024 * 1024
    max_active_commands: int = 2
    max_patch_bytes: int = 32 * 1024 * 1024
    state_dir: Path = field(default_factory=lambda: locations()[2])
    config_path: Path | None = None
    protected_paths: list[Path] = field(default_factory=list)
    additional_roots: list[dict[str, str]] = field(default_factory=list)

    def __post_init__(self):
        primary_path = Path(os.path.abspath(Path(self.root).expanduser()))
        self.root = primary_path.resolve()
        self._root_aliases = [(primary_path, self.root)] if primary_path != self.root else []
        self.state_dir = Path(self.state_dir).expanduser().resolve()
        if any(self.root == parent or (self.root.exists() and self.root.samefile(parent))
               for parent in Path.home().resolve().parents):
            raise Fault('ROOT_TOO_BROAD', '不允许把根目录设置为 HOME 的上级。', str(self.root),
                        '使用 HOME、本机项目目录或明确授权的外部数据目录。')
        if not self.root.is_dir():
            raise Fault('INVALID_ROOT', '授权根目录不存在。', str(self.root), '先创建或选择已存在的目录。')
        if self.mode not in ('read_only', 'read_write') or self.default_policy not in ('allow', 'deny'):
            raise ValueError('mode must be read_only/read_write; default_policy must be allow/deny')
        if not isinstance(self.additional_roots, list):
            raise ValueError('additional_roots 必须是目录配置列表')
        normalized, seen, configured_paths = [], {self.root}, []
        for entry in self.additional_roots:
            if not isinstance(entry, dict) or set(entry) - {'path', 'mode'}:
                raise ValueError('additional_roots 每项只接受 path 和 mode')
            value, mode = entry.get('path'), entry.get('mode', 'read_only')
            if not isinstance(value, str) or not value or '\x00' in value or len(value) > 4096:
                raise ValueError('附加目录 path 必须是非空路径字符串，长度不超过 4096')
            if mode not in ('read_only', 'read_write'):
                raise ValueError('附加目录 mode 必须是 read_only 或 read_write')
            expanded = self._expand_temp_path(value)
            path = Path(expanded).expanduser()
            if not path.is_absolute() or '..' in path.parts:
                raise ValueError('附加目录必须使用绝对路径或 ~/ 路径，不能含有父目录跳转')
            lexical = Path(os.path.abspath(path))
            actual = lexical.resolve()
            if any(actual == parent or (actual.exists() and actual.samefile(parent))
                   for parent in Path.home().resolve().parents):
                raise Fault('ROOT_TOO_BROAD', '附加目录不能是 HOME 的上级。', str(actual),
                            '选择具体的临时目录或外部数据目录。')
            if not actual.is_dir():
                raise Fault('INVALID_ROOT', '附加授权目录不存在。', str(actual),
                            '先创建目录；检查启动 MCP 的用户和临时目录环境变量。')
            if any(actual.samefile(root) for root in seen):
                raise ValueError('附加目录与主根目录或其他附加目录重复')
            seen.add(actual)
            configured_paths.extend((lexical, actual))
            normalized.append({'path': str(actual), 'mode': mode})
            if lexical != actual:
                self._root_aliases.append((lexical, actual))
        self.additional_roots = normalized
        self._root_aliases.sort(key=lambda pair: len(pair[0].parts), reverse=True)
        for name in ('allow', 'deny', 'force_allow', 'write_roots', 'git_push_remotes'):
            if not isinstance(getattr(self, name), list) or not all(isinstance(x, str) for x in getattr(self, name)):
                raise ValueError(f'{name} must be a list of strings')
        # 保留旧接口的精确路径例外语义，不自动生成逐文件例外。
        if any(any(c in x for c in '*?[') for x in self.force_allow):
            raise ValueError('force_allow accepts exact relative file paths only, not wildcards')
        for name in ('max_file_size', 'max_text_output_bytes', 'max_directory_entries', 'max_search_files',
                     'max_search_results', 'max_image_pixels', 'max_image_bytes'):
            n = getattr(self, name)
            if type(n) is not int or n <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('enable_commands','enable_git_push','enable_codex_history'):
            if type(getattr(self,name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
        if not isinstance(self.codex_history_home,str) or '\0' in self.codex_history_home:
            raise ValueError('codex_history_home must be a local path string')
        if self.git_credential_helper not in ('','osxkeychain','manager','libsecret'):
            raise ValueError('git_credential_helper must be a supported native helper name')
        for name in ('git_user_name','git_user_email'):
            value=getattr(self,name)
            if not isinstance(value,str) or len(value)>256 or any(c in value for c in '\r\n\0'):
                raise ValueError(f'invalid {name}')
        for name, ceiling in (('max_command_timeout',3600),('max_command_output_bytes',8*1024*1024),
                               ('max_active_commands',8),('max_patch_bytes',128*1024*1024)):
            value=getattr(self,name)
            if type(value) is not int or not 1<=value<=ceiling:
                raise ValueError(f'{name} must be 1..{ceiling}')
        # Limits are both resource controls and transport guarantees, not just defaults.
        if self.max_file_size > 256 * 1024 * 1024 or self.max_image_bytes > 4 * 1024 * 1024:
            raise ValueError('max_file_size <= 256 MiB; max_image_bytes <= 4 MiB')
        config, app, state = locations()
        self.protected_paths += [config, app, state, self.state_dir,
            Path.home() / '.config/home-readonly-mcp', Path.home() / '.local/share/home-readonly-mcp',
            Path(__file__).resolve().parent, Path.home()/'.local/bin/local-mcp',
            Path.home()/'.local/bin/home-readonly-mcp']
        if self.config_path:
            self.protected_paths.append(Path(self.config_path).expanduser().resolve())
        self.protected_paths = [Path(x).expanduser().resolve() for x in self.protected_paths]
        self.protected_credential_paths = credential_paths()
        for path in configured_paths:
            self._check_protected_path(path)

    @classmethod
    def from_file(cls, path=None):
        p = Path(path or os.environ.get('LOCAL_MCP_CONFIG') or
                 os.environ.get('HOME_READONLY_MCP_CONFIG') or locations()[0] / 'config.json').expanduser()
        if not p.exists():
            raise Fault('CONFIG_MISSING', '尚未配置 MCP。', str(p), '运行安装脚本或 local-mcp configure。')
        data = json.loads(p.read_text(encoding='utf-8'))
        if not isinstance(data, dict):
            raise ValueError('config must be an object')
        names = set(cls.__dataclass_fields__) - {'config_path', 'protected_paths', 'state_dir'}
        return cls(**{k: v for k, v in data.items() if k in names}, config_path=p)

    def relative(self, path):
        p = Path(path)
        self.root_for(p)
        # 主目录保持旧的相对路径；外部目录使用可直接传回工具的绝对路径。
        rel = self._relative_in_root(p, self.root)
        return rel.as_posix() if rel is not None else p.as_posix()

    @staticmethod
    def _expand_temp_path(value):
        def replace(match):
            name = match.group(1)
            if name == 'TEMP_DIR':
                return tempfile.gettempdir()
            if name not in ('TMPDIR', 'TEMP', 'TMP'):
                raise ValueError('附加目录只支持 ${TEMP_DIR}、${TMPDIR}、${TEMP}、${TMP}')
            if not os.environ.get(name):
                raise ValueError(f'临时目录变量 {name} 未设置；改用 ${{TEMP_DIR}} 或绝对路径')
            return os.environ[name]
        return re.sub(r'\$\{([^}]+)\}', replace, value)

    def _matching_roots(self, path):
        p = Path(path)
        roots = [(self.root, self.mode)] + [(Path(x['path']), x['mode']) for x in self.additional_roots]
        found = [(root, mode) for root, mode in roots if self._relative_in_root(p, root) is not None]
        return sorted(found, key=lambda item: len(item[0].parts), reverse=True)

    @staticmethod
    def _relative_in_root(path, root):
        """目录身份校验兼容大小写／Unicode 别名，不把链接当作大小写别名。"""
        if len(path.parts) < len(root.parts):
            return None
        prefix = Path(*path.parts[:len(root.parts)])
        relative = Path(*path.parts[len(root.parts):])
        if str(prefix) == str(root):
            return relative
        key = lambda value: unicodedata.normalize('NFD', str(value)).casefold()
        if key(prefix) != key(root):
            return None
        try:
            if any(p.is_symlink() or getattr(p, 'is_junction', lambda: False)()
                   for p in (prefix, *prefix.parents)):
                return None
            return relative if prefix.samefile(root) else None
        except FileNotFoundError:
            return None

    def _check_protected_path(self, path):
        if any(self._relative_in_root(path, blocked) is not None for blocked in self.protected_paths):
            raise Fault('PROTECTED_RUNTIME', 'MCP 配置、程序或私有状态不可通过工具访问。',
                        '禁止远程修改自身权限、读取密钥配置或绕过备份策略。', '请在本机管理配置。')
        hit = next((blocked for blocked in self.protected_credential_paths
                    if self._relative_in_root(path, blocked) is not None), None)
        if hit:
            raise Fault('POLICY_DENIED', '目标位于受保护的用户级凭据存储位置。', 'protected_credential_path',
                        '选择已授权的项目或数据路径；项目中的同名文件不受此保护。', matched_rule=str(hit))

    def root_for(self, path):
        """返回最具体的授权根，供文件句柄、检索和 Git 边界共同使用。"""
        found = self._matching_roots(path)
        if not found:
            raise Fault('OUTSIDE_ROOT', '路径超出授权根目录。', '路径不在主根目录或附加目录内。',
                        '使用已授权目录；只能在本机修改 root 或 additional_roots。')
        return found[0][0]

    def _normalize_root_alias(self, path):
        for alias, actual in self._root_aliases:
            if path.is_relative_to(alias):
                if alias.resolve() != actual:
                    raise Fault('ROOT_ALIAS_CHANGED', '配置的目录别名已指向其他位置。', str(alias),
                                '在本机检查目录并重启 MCP；不会自动授权新的链接目标。')
                return actual / path.relative_to(alias)
        return path

    def rule(self, rel):
        chain = [rel] + [p.as_posix() for p in Path(rel).parents if str(p) != '.']
        if rel.casefold() in {x.replace('\\', '/').removeprefix('~/').casefold() for x in self.force_allow}:
            return True, 'force_allow_exact', rel
        for name in chain:
            for pat in self.deny:
                if matches(name, pat):
                    return False, 'deny', pat
        if any(matches(rel, p) for p in self.allow):
            return True, 'allow', ''
        return self.default_policy == 'allow', 'default_' + self.default_policy, ''

    def resolve(self, path='.', *, write=False):
        if not isinstance(path, str) or '\x00' in path or len(path) > 4096:
            raise ValueError('path must be a string <=4096 characters without NUL')
        supplied = Path(path).expanduser()
        if '..' in supplied.parts:
            raise Fault('PATH_TRAVERSAL', '拒绝 ../ 路径。', '父目录跳转不属于受支持路径形式。', '改用 root 内相对路径。')
        candidate = supplied if supplied.is_absolute() else self.root / supplied
        supplied_path = Path(os.path.abspath(candidate))
        lexical = self._normalize_root_alias(supplied_path)
        scopes = self._matching_roots(lexical)
        if scopes:
            root = scopes[0][0]
            lexical = root / self._relative_in_root(lexical, root)
        actual = lexical.resolve()
        checked = [lexical, actual]
        if supplied_path != lexical and self._matching_roots(supplied_path):
            checked.insert(0, supplied_path)
        if supplied_path != lexical:
            self._check_protected_path(supplied_path)
        for p in checked:
            self.root_for(p)
            scopes = self._matching_roots(p)
            self._check_protected_path(p)
            # 重叠目录的规则同时校验，不能借更窄的根跳过原有 deny/allow。
            for root, _ in scopes:
                rel = self._relative_in_root(p, root).as_posix()
                ok, reason, pattern = self.rule(rel)
                if not ok:
                    raise Fault('POLICY_DENIED', '黑白名单拒绝访问。', reason,
                                '检查 policy_info；仅在本机审核并调整规则。', path=self.relative(p), matched_rule=pattern)
        if write:
            if self.mode != 'read_write':
                raise Fault('READ_ONLY_MODE', '当前服务为只读模式。', '配置 mode=read_only。',
                            '在本机设置 read_write 并重启/刷新客户端；提示词不能提升权限。')
            if any(p == root for p in checked for root, _ in self._matching_roots(p)):
                raise Fault('ROOT_MUTATION_DENIED', '禁止修改根目录本身。', '根目录是安全边界。', '指定根目录内的文件。')
            if lexical != actual:
                raise Fault('SYMLINK_WRITE_DENIED', '不通过符号链接写文件。', '写入路径含链接或重解析组件。',
                            '使用真实的 root 内目标路径。')
            for p in checked:
                root, mode = self._matching_roots(p)[0]
                if mode != 'read_write':
                    raise Fault('READ_ONLY_ROOT', '附加授权目录为只读。', str(root),
                                '在本机明确设置该目录 mode=read_write 并重启 MCP。')
                main_rel = self._relative_in_root(p, self.root)
                if main_rel is not None:
                    rel = main_rel.as_posix()
                    if self.write_roots and not any(matches(rel, x) for x in self.write_roots):
                        raise Fault('WRITE_SCOPE_DENIED', '目标不在可写子目录内。', 'write_roots 限制写入范围。',
                                    '使用允许的项目目录，或在本机修改 write_roots。', path=rel)
        return actual

    def require(self, path, *, write=False, must_exist=True):
        p = self.resolve(str(path), write=write)
        if must_exist and not p.exists():
            raise FileNotFoundError(str(path))
        return p

    def summary(self):
        return {'root': str(self.root), 'mode': self.mode, 'default_policy': self.default_policy,
                'additional_roots': [{**entry, 'effective_mode': entry['mode'] if self.mode == 'read_write'
                                      else 'read_only'} for entry in self.additional_roots],
                'allow': self.allow, 'deny': self.deny, 'force_allow': self.force_allow,
                'write_roots': self.write_roots,
                'credential_protection': 'explicit_user_paths',
                'protected_credentials': [str(path) for path in self.protected_credential_paths],
                'max_file_size': self.max_file_size, 'max_text_output_bytes': self.max_text_output_bytes,
                'policy_editable_via_mcp': False,
                'shell_enabled': self.enable_commands and self.mode == 'read_write',
                'git_push_enabled': self.enable_git_push and self.mode == 'read_write',
                'git_push_remotes': self.git_push_remotes,
                'max_active_commands': self.max_active_commands,
                'max_command_timeout': self.max_command_timeout,
                'command_security': 'Explicitly opted-in shell is NOT an OS sandbox; root/deny rules only constrain file tools and command cwd.',
                'warning': 'HOME-wide read_write grants broad file access; prefer project write_roots.'}


# Compatibility name for callers of the old package.
PolicyError = Fault
