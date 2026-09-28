"""原生库被隔离时应在加载前报错，安装修复必须先完整校验。"""
import hashlib
import importlib.util
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from home_readonly_mcp.errors import Fault


def test_image_blocked_before_import(space, monkeypatch):
    from home_readonly_mcp import dependencies, media
    def blocked(package):
        raise Fault('DEPENDENCY_QUARANTINED', '测试隔离', '测试', '重装')
    monkeypatch.setattr(dependencies, 'check_native_quarantine', blocked)
    monkeypatch.setattr(dependencies.importlib, 'import_module', lambda *_: pytest.fail('不得加载被隔离库'))
    with pytest.raises(Fault, match='测试隔离') as got:
        media.image_content(b'irrelevant', 'a.jpg', space[2])
    assert got.value.code == 'DEPENDENCY_QUARANTINED'


@pytest.mark.parametrize('error,code', [
    (ModuleNotFoundError("No module named PIL", name='PIL'), 'DEPENDENCY_MISSING'),
    (ModuleNotFoundError("No module named PIL._imaging", name='PIL._imaging'), 'DEPENDENCY_LOAD_FAILED'),
    (ImportError('dlopen: blocked by system policy'), 'DEPENDENCY_LOAD_FAILED'),
    (OSError('incompatible architecture'), 'DEPENDENCY_LOAD_FAILED'),
])
def test_import_failure_classification(monkeypatch, error, code):
    from home_readonly_mcp import dependencies
    monkeypatch.setattr(dependencies, 'check_native_quarantine', lambda *_: None)
    def fail(*_): raise error
    monkeypatch.setattr(dependencies.importlib, 'import_module', fail)
    with pytest.raises(Fault) as got: dependencies.load('PIL.Image', 'Pillow')
    assert got.value.code == code


def wheel(tmp_path):
    path = tmp_path/'demo-1.0-py3-none-any.whl'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('demo-1.0.dist-info/METADATA', 'Name: demo\nVersion: 1.0\n')
        z.writestr('demo/a.so', b'native one')
        z.writestr('demo/b.dylib', b'native two')
    return path


def test_official_wheel_checksum_required(tmp_path, monkeypatch):
    from home_readonly_mcp import wheel_install
    path = wheel(tmp_path)
    metadata = {'urls': [{'filename': path.name, 'digests': {'sha256': '0'*64}}]}
    monkeypatch.setattr(wheel_install, 'release_metadata', lambda *_: metadata)
    with pytest.raises(ValueError, match='SHA256'): wheel_install.verify_wheel(path)
    metadata['urls'][0]['digests']['sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert wheel_install.verify_wheel(path)['demo/a.so'] == hashlib.sha256(b'native one').hexdigest()


def test_no_partial_clear_on_mismatch(tmp_path, monkeypatch):
    from home_readonly_mcp import wheel_install
    site = tmp_path/'site'; site.mkdir()
    (site/'a.so').write_bytes(b'ok'); (site/'b.so').write_bytes(b'tampered')
    expected = {x: hashlib.sha256(b'ok').hexdigest() for x in ('a.so', 'b.so')}
    cleared = []
    monkeypatch.setattr(wheel_install, 'remove_quarantine', lambda *a: cleared.append(a))
    with pytest.raises(ValueError, match='完整性'): wheel_install.repair_native_files(site, expected)
    assert not cleared


def test_only_verified_native_quarantine_removed(tmp_path, monkeypatch):
    from home_readonly_mcp import wheel_install
    (tmp_path/'a.so').write_bytes(b'ok'); (tmp_path/'unrelated.txt').write_bytes(b'leave')
    cleared = []
    monkeypatch.setattr(wheel_install, 'has_quarantine', lambda *_: not cleared)
    monkeypatch.setattr(wheel_install, 'remove_quarantine', lambda fd: cleared.append(fd))
    result = wheel_install.repair_native_files(tmp_path, {'a.so': hashlib.sha256(b'ok').hexdigest()})
    assert result['quarantine_removed'] == 1
    assert len(cleared) == 1


@pytest.mark.skipif(sys.platform == 'win32', reason='Windows 符号链接需要额外权限')
def test_native_symlink_refused(tmp_path):
    from home_readonly_mcp import wheel_install
    (tmp_path/'real').write_bytes(b'ok'); (tmp_path/'a.so').symlink_to(tmp_path/'real')
    with pytest.raises(ValueError):
        wheel_install.repair_native_files(tmp_path, {'a.so': hashlib.sha256(b'ok').hexdigest()})


def test_media_self_test_exercises_jpeg_and_pdf(space):
    pytest.importorskip('PIL.Image'); pytest.importorskip('pypdfium2')
    from home_readonly_mcp.dependencies import media_self_test
    r = media_self_test()
    assert r['jpeg_image_content'] and r['pdf_image_content'] and r['pdf_text']


def test_failed_media_keeps_previous_install(space, monkeypatch):
    from home_readonly_mcp.policy import locations
    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('bootstrap_test', repo/'bootstrap.py')
    bootstrap = importlib.util.module_from_spec(spec); spec.loader.exec_module(bootstrap)
    app = locations()[1]; app.mkdir(parents=True)
    pointer = app/'current.json'; pointer.write_text('previous installation')
    monkeypatch.setattr(sys, 'argv', ['bootstrap.py', '--root', str(space[1])])
    # 不安装真实依赖；在媒体自检失败这一边界验证不会触碰 active pointer。
    monkeypatch.setattr(bootstrap.venv.EnvBuilder, 'create', lambda *a: None)
    from home_readonly_mcp import wheel_install
    monkeypatch.setattr(wheel_install, 'install_macos_wheels', lambda *a: None)
    def run(argv, **kwargs):
        if 'media-self-test' in argv: raise subprocess.CalledProcessError(1, argv)
        return subprocess.CompletedProcess(argv, 0)
    monkeypatch.setattr(bootstrap.subprocess, 'run', run)
    assert bootstrap.main() == 1
    assert pointer.read_text() == 'previous installation'


@pytest.mark.skipif(sys.platform != 'darwin', reason='macOS 实际隔离属性接口')
def test_real_quarantine_preflight_and_verified_repair(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from home_readonly_mcp import dependencies, wheel_install
    from home_readonly_mcp.macos_quarantine import has_quarantine
    path = tmp_path/'fake.so'; path.write_bytes(b'synthetic native fixture, never loaded')
    subprocess.run(['/usr/bin/xattr', '-w', 'com.apple.quarantine', '0081;12345678;test;', str(path)], check=True)
    subprocess.run(['/usr/bin/xattr', '-w', 'test.preserved', 'keep', str(path)], check=True)
    dist = SimpleNamespace(files=['fake.so'], locate_file=lambda x: tmp_path/x)
    monkeypatch.setattr(dependencies.importlib.metadata, 'distribution', lambda _: dist)
    with pytest.raises(Fault) as got: dependencies.check_native_quarantine('test')
    assert got.value.code == 'DEPENDENCY_QUARANTINED'
    result = wheel_install.repair_native_files(tmp_path, {'fake.so': hashlib.sha256(path.read_bytes()).hexdigest()})
    assert result['quarantine_removed'] == 1 and not has_quarantine(path)
    assert subprocess.check_output(['/usr/bin/xattr', '-p', 'test.preserved', str(path)]).strip() == b'keep'
    dependencies.check_native_quarantine('test')
