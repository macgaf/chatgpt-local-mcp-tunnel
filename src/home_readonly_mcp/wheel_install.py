"""macOS 安装专用：校验官方 wheel，再限定处理新环境中的原生库隔离标记。

不作为 MCP 工具暴露；不修改系统策略、签名或外部环境。PyPI 哈希验证不等于 Apple 公证。
"""
from __future__ import annotations
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import tempfile
from urllib.parse import quote
from urllib.request import urlopen
import zipfile
from .macos_quarantine import has_quarantine, remove_quarantine


def release_metadata(name, version):
    url = f'https://pypi.org/pypi/{quote(name, safe="")}/{quote(version, safe="")}/json'
    with urlopen(url, timeout=30) as response:
        if not response.url.startswith('https://pypi.org/'):
            raise ValueError('拒绝非官方 PyPI 元数据地址')
        data = response.read(8*1024*1024+1)
    if len(data) > 8*1024*1024:
        raise ValueError('PyPI 元数据超过上限')
    return json.loads(data)


def verify_wheel(path):
    """返回已验证 wheel 内原生文件的 SHA256；此时尚未安装或加载它们。"""
    body = path.read_bytes()
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        metadata = [n for n in names if n.endswith('.dist-info/METADATA')]
        if len(metadata) != 1 or len(names) != len(set(names)):
            raise ValueError('wheel 元数据或成员不唯一')
        fields = BytesParser().parsebytes(archive.read(metadata[0]))
        release = release_metadata(fields['Name'], fields['Version'])
        expected = [f['digests']['sha256'] for f in release['urls'] if f['filename'] == path.name]
        if len(expected) != 1 or hashlib.sha256(body).hexdigest() != expected[0]:
            raise ValueError(f'官方 PyPI SHA256 校验失败：{path.name}')
        native = {}
        for name in names:
            parts = PurePosixPath(name).parts
            if not parts or name.startswith('/') or '..' in parts or '\\' in name:
                raise ValueError('wheel 含不安全路径')
            if name.endswith(('.so', '.dylib')):
                if any(p.endswith('.data') for p in parts):
                    raise ValueError('不自动处理需要重定位的原生 wheel 文件')
                native[name] = hashlib.sha256(archive.read(name)).hexdigest()
    return native


def repair_native_files(site, expected):
    """先校验全部候选，再仅移除这些文件的 quarantine；未知、篡改或链接文件均拒绝。"""
    site = site.resolve()
    actual = {p.relative_to(site).as_posix() for p in site.rglob('*') if p.name.endswith(('.so', '.dylib'))}
    if actual != set(expected):
        raise ValueError('原生库清单不一致，拒绝处理隔离标记')
    paths = []
    for name, checksum in expected.items():
        path = site/name
        current = path
        while current != site:
            if current.is_symlink(): raise ValueError('原生库路径包含符号链接')
            if site not in current.parents: raise ValueError('原生库路径越界')
            current = current.parent
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError(f'原生库完整性校验失败：{name}')
        paths.append((path, checksum))
    count = 0
    for path, checksum in paths:
        # 文件描述符固定目标；修改前复核，避免路径在校验后被替换。
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        try:
            with os.fdopen(os.dup(fd), 'rb') as file:
                if hashlib.sha256(file.read()).hexdigest() != checksum:
                    raise ValueError('原生库在校验后发生变化')
            if os.fstat(fd).st_nlink != 1: raise ValueError('拒绝原生库硬链接')
            if has_quarantine(fd):
                remove_quarantine(fd)
                if has_quarantine(fd): raise ValueError('隔离标记处理未生效')
                count += 1
        finally:
            os.close(fd)
    return {'native_files_verified': len(paths), 'quarantine_removed': count}


def install_macos_wheels(python, packages, env):
    """仅用于安装器刚创建的 venv；网络或校验失败时不降级。"""
    pip = [str(python), '-I', '-m', 'pip', '--isolated', '--disable-pip-version-check']
    # 明确禁用额外 pip 配置，避免额外 index、target 或安装钩子改变校验范围。
    env = {**env, 'PIP_CONFIG_FILE': os.devnull}
    with tempfile.TemporaryDirectory(prefix='local-mcp-wheels-') as folder:
        subprocess.run([*pip, 'download', '--only-binary=:all:', '--index-url', 'https://pypi.org/simple',
                        '--dest', folder, *packages], env=env, check=True)
        wheels = sorted(Path(folder).glob('*.whl'))
        if not wheels: raise ValueError('未获取 wheel')
        expected = {}
        for wheel in wheels:
            files = verify_wheel(wheel)
            if expected.keys() & files.keys(): raise ValueError('wheel 原生文件路径冲突')
            expected.update(files)
        subprocess.run([*pip, 'install', '--no-index', '--no-deps', '--no-compile', *map(str, wheels)], env=env, check=True)
        site = Path(subprocess.check_output([str(python), '-I', '-c',
                    'import sysconfig; print(sysconfig.get_path("platlib"))'], env=env, text=True).strip())
        if Path(python).parent.parent.resolve() not in site.resolve().parents:
            raise ValueError('安装目标不属于本次虚拟环境')
        result = repair_native_files(site, expected)
        print(json.dumps({'verification': 'official_pypi_sha256_and_installed_native_bytes', **result}), flush=True)
        return result
