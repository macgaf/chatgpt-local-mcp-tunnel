"""Local-only security settings. No MCP tool can change these settings."""
from __future__ import annotations
from dataclasses import dataclass, field
import fnmatch
import json
import os
from pathlib import Path
from .errors import Fault

APP = 'chatgpt-local-mcp-tunnel'
HARD_DENY = [
    '.ssh/**', '**/.ssh/**', '.gnupg/**', '.aws/**', '.azure/**', '.kube/**',
    '.codex/auth.json', '.claude/.credentials.json', '.docker/config.json',
    '.git-credentials', '.netrc', '.npmrc', '.pypirc',
    'Library/Keychains/**', 'Library/**/Cookies*', 'Library/**/Login Data*',
    'Library/Application Support/Google/Chrome/**', 'Library/Application Support/Firefox/**',
    'Library/Application Support/Microsoft Edge/**', 'Library/Safari/**',
    '.config/google-chrome/**', '.config/chromium/**', '.mozilla/**',
    '.local/share/keyrings/**', '.local/share/kwalletd/**', '.config/kwalletrc',
    'AppData/**/Microsoft/Credentials/**', 'AppData/**/Microsoft/Vault/**',
    'AppData/**/Google/Chrome/User Data/**', 'AppData/**/Microsoft/Edge/User Data/**',
    '**/id_rsa', '**/id_ed25519', '**/id_ecdsa',
]
DEFAULT_DENY = ['**/.env', '**/.env.*', '**/*.pem', '**/*.key', '**/*.p12', '**/*.pfx',
    '**/*credentials*', '**/secrets/**', '**/.git/**', '**/node_modules/**', '**/.venv/**',
    '**/__pycache__/**', '.Trash/**', 'Library/Caches/**',
    '.zsh_history', '.bash_history', '.python_history', '.config/**/tokens*',
    '.config/**/secrets*', '.config/**/auth.json']


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

    def __post_init__(self):
        self.root = Path(self.root).expanduser().resolve()
        self.state_dir = Path(self.state_dir).expanduser().resolve()
        if self.root in Path.home().resolve().parents:
            raise Fault('ROOT_TOO_BROAD', '不允许把根目录设置为 HOME 的上级。', str(self.root),
                        '使用 HOME、本机项目目录或明确授权的外部数据目录。')
        if not self.root.is_dir():
            raise Fault('INVALID_ROOT', '授权根目录不存在。', str(self.root), '先创建或选择已存在的目录。')
        if self.mode not in ('read_only', 'read_write') or self.default_policy not in ('allow', 'deny'):
            raise ValueError('mode must be read_only/read_write; default_policy must be allow/deny')
        for name in ('allow', 'deny', 'force_allow', 'write_roots', 'git_push_remotes'):
            if not isinstance(getattr(self, name), list) or not all(isinstance(x, str) for x in getattr(self, name)):
                raise ValueError(f'{name} must be a list of strings')
        # Exact exceptions only: no broad wildcard can expose credentials by accident.
        if any(any(c in x for c in '*?[') for x in self.force_allow):
            raise ValueError('force_allow accepts exact relative file paths only, not wildcards')
        for name in ('max_file_size', 'max_text_output_bytes', 'max_directory_entries', 'max_search_files',
                     'max_search_results', 'max_image_pixels', 'max_image_bytes'):
            n = getattr(self, name)
            if type(n) is not int or n <= 0:
                raise ValueError(f'{name} must be a positive integer')
        for name in ('enable_commands','enable_git_push'):
            if type(getattr(self,name)) is not bool:
                raise ValueError(f'{name} must be a boolean')
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
        try:
            return Path(path).relative_to(self.root).as_posix()
        except ValueError:
            raise Fault('OUTSIDE_ROOT', '路径超出授权根目录。', '真实路径不在 root 内。',
                        '使用 root 内路径；只有用户在本机可以修改 root。') from None

    def rule(self, rel):
        chain = [rel] + [p.as_posix() for p in Path(rel).parents if str(p) != '.']
        for name in chain:
            for pat in HARD_DENY:
                if matches(name, pat):
                    return False, 'protected_credential', pat
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
        lexical = Path(os.path.abspath(candidate))
        actual = lexical.resolve()
        for p in (lexical, actual):
            rel = self.relative(p)
            if any(p == blocked or blocked in p.parents for blocked in self.protected_paths):
                raise Fault('PROTECTED_RUNTIME', 'MCP 配置、程序或私有状态不可通过工具访问。',
                            '禁止远程修改自身权限、读取密钥配置或绕过备份策略。', '请在本机管理配置。')
            # A narrower root must not turn ~/.ssh or browser stores into ordinary files.
            home = Path.home().resolve()
            if p == home or home in p.parents:
                home_rel = p.relative_to(home).as_posix()
                chain = [home_rel] + [x.as_posix() for x in Path(home_rel).parents if str(x) != '.']
                hit = next((pat for item in chain for pat in HARD_DENY if matches(item, pat)), None)
                if hit:
                    raise Fault('POLICY_DENIED', '系统凭据目录始终受保护。', 'protected_credential',
                                '选择普通项目目录；缩小 root 不会解除凭据保护。', matched_rule=hit)
            ok, reason, pattern = self.rule(rel)
            if not ok:
                raise Fault('POLICY_DENIED', '黑白名单拒绝访问。', reason,
                            '检查 policy_info；仅在本机审核并调整规则。', path=rel, matched_rule=pattern)
        if write:
            if self.mode != 'read_write':
                raise Fault('READ_ONLY_MODE', '当前服务为只读模式。', '配置 mode=read_only。',
                            '在本机设置 read_write 并重启/刷新客户端；提示词不能提升权限。')
            if actual == self.root:
                raise Fault('ROOT_MUTATION_DENIED', '禁止修改根目录本身。', '根目录是安全边界。', '指定根目录内的文件。')
            if lexical != actual:
                raise Fault('SYMLINK_WRITE_DENIED', '不通过符号链接写文件。', '写入路径含链接或重解析组件。',
                            '使用真实的 root 内目标路径。')
            rel = self.relative(actual)
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
                'allow': self.allow, 'deny': self.deny, 'force_allow': self.force_allow,
                'write_roots': self.write_roots, 'protected_credentials': HARD_DENY,
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
