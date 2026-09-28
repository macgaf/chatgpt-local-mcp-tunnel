"""按需加载媒体依赖；诊断不执行被 macOS 隔离的原生库。"""
from __future__ import annotations
import base64
import importlib
import importlib.metadata
from io import BytesIO
from pathlib import Path
import json
import subprocess
import sys
import tempfile

from .errors import Fault, redact


def check_native_quarantine(package):
    if sys.platform != 'darwin':
        return
    from .macos_quarantine import has_quarantine
    try:
        dist = importlib.metadata.distribution(package)
    except importlib.metadata.PackageNotFoundError:
        return  # 由真正的 import 区分缺少顶层包和缺少内部模块。
    for entry in dist.files or ():
        if not str(entry).endswith(('.so', '.dylib')):
            continue
        path = Path(dist.locate_file(entry))
        if path.exists() and has_quarantine(path):
            raise Fault('DEPENDENCY_QUARANTINED', '媒体依赖带有 macOS 隔离标记，已停止加载。',
                        '加载原生库可能触发 Gatekeeper 弹窗；包存在不代表可用。',
                        '使用新版完整安装器重新安装；安装器校验官方 wheel 与原生文件后定向处理。不要反复调用或批量清除安全属性。',
                        package=package, file=str(path))


def load(module, package):
    check_native_quarantine(package)
    try:
        return importlib.import_module(module)
    except (ImportError, OSError) as exc:
        if isinstance(exc, ModuleNotFoundError) and exc.name == module.split('.')[0]:
            raise Fault('DEPENDENCY_MISSING', f'需要可选依赖 {package}。', '当前 Python 环境未安装对应适配器。',
                        '重新运行完整安装器安装媒体组件。', package=package) from exc
        raise Fault('DEPENDENCY_LOAD_FAILED', f'{package} 已安装但无法加载。',
                    f'{type(exc).__name__}: {redact(str(exc))[:500]}',
                    '运行 local-mcp doctor；检查系统拦截、架构和原生库完整性，随后重新安装。',
                    package=package) from exc


def _pdf_fixture():
    stream = b'BT /F1 12 Tf 10 30 Td (MCP media test) Tj ET\n'
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 160 80] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    out = b'%PDF-1.4\n'; offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out)); out += str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref = len(out); out += b'xref\n0 6\n0000000000 65535 f \n'
    for offset in offsets: out += f'{offset:010d} 00000 n \n'.encode()
    return out+f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()


def media_self_test():
    """走实际服务方法，验证 JPEG 解码、PDF 文字和返回的图片内容；不访问用户文件。"""
    from .policy import Policy
    from .service import HomeService
    Image = load('PIL.Image', 'Pillow')
    # pdfium 的动态库属于独立的 pypdfium2_raw 目录，同一个发行包。
    load('pypdfium2', 'pypdfium2')
    with tempfile.TemporaryDirectory(prefix='local-mcp-media-') as folder:
        root = Path(folder)
        Image.new('RGB', (32, 16), (20, 130, 220)).save(root/'probe.jpg', 'JPEG')
        (root/'probe.pdf').write_bytes(_pdf_fixture())
        service = HomeService(Policy(root=root, state_dir=root/'state'))
        try:
            for result in (service.read_image('probe.jpg'), service.render_pdf_page('probe.pdf', max_edge=160)):
                block = next(b for b in result['content'] if b['type'] == 'image')
                with Image.open(BytesIO(base64.b64decode(block['data'], validate=True))) as image:
                    image.load()
                    if min(image.size) <= 0: raise ValueError('媒体自检返回空图片')
            if 'MCP media test' not in service.read_document('probe.pdf')['content']:
                raise ValueError('PDF 文字自检失败')
        finally:
            service.close()
    return {'ok': True, 'jpeg_image_content': True, 'pdf_image_content': True, 'pdf_text': True,
            'client_visual_consumption_tested': False}


def media_probe():
    """子进程承载原生库：崩溃和超时均转换为明确失败，不拖死 doctor。"""
    source = str(Path(__file__).resolve().parents[1])
    code = (f'import sys,json; sys.path.insert(0,{source!r})\n'
            'from home_readonly_mcp.dependencies import media_self_test\n'
            'from home_readonly_mcp.errors import normalize_error\n'
            'try: print(json.dumps(media_self_test()))\n'
            'except Exception as exc: print(json.dumps(normalize_error(exc).payload())); sys.exit(1)\n')
    try:
        proc = subprocess.run([sys.executable, '-I', '-c', code], capture_output=True,
                              text=True, encoding='utf-8', timeout=30)
    except subprocess.TimeoutExpired as exc:
        raise Fault('MEDIA_SELF_TEST_TIMEOUT', '媒体自检超时。', '原生库未在 30 秒内完成加载或处理。',
                    '检查 macOS 弹窗和依赖加载日志；不要反复重试。') from exc
    try:
        result = json.loads(proc.stdout)
    except (ValueError, TypeError):
        result = {}
    if proc.returncode == 0 and result.get('ok'):
        return result
    error = result.get('error')
    if error:
        raise Fault(error['code'], error['message'], error['cause'], error['remediation'], **error.get('details', {}))
    raise Fault('MEDIA_SELF_TEST_FAILED', '媒体子进程未完成自检。',
                f'退出码 {proc.returncode}；{redact(proc.stderr)[-500:]}',
                '检查原生依赖和操作系统诊断；安装器不会切换到此版本。')
