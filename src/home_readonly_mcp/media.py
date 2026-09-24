"""In-memory previews. Original files are never re-encoded or extracted in place."""
from __future__ import annotations
import base64
from io import BytesIO
import json
import mimetypes
from pathlib import PurePosixPath
import stat
import warnings
import zipfile
from urllib.parse import quote
from .errors import Fault
from .storage import digest


def text_content(data):
    return {'type': 'text', 'text': json.dumps(data, ensure_ascii=False)}


def need(package, extra):
    raise Fault('DEPENDENCY_MISSING', f'需要可选依赖 {package}。', '当前 Python 环境未安装对应文件适配器。',
                f'重新运行安装脚本并包含 {extra} 组件，或在安装虚拟环境中安装 {package}。', package=package)


def image_content(data, name, policy, *, max_edge=1600, crop=None):
    try:
        from PIL import Image, ImageOps
    except ImportError:
        need('Pillow', 'media')
    if not 64 <= max_edge <= 4096:
        raise ValueError('max_edge must be between 64 and 4096')
    if name.lower().endswith(('.heic', '.heif')):
        try:
            import pillow_heif
            pillow_heif.register_heif_opener()
        except ImportError:
            need('pillow-heif', 'heif')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as original:
                if original.width * original.height > policy.max_image_pixels:
                    raise Fault('IMAGE_PIXEL_LIMIT', '图像解码像素数超过上限。',
                                str(original.size), '在本机增加 max_image_pixels 或生成较小预览。')
                raw_size = original.size
                orientation = original.getexif().get(274, 1)
                im = ImageOps.exif_transpose(original)
                oriented_size = im.size
                box = [0, 0, im.width, im.height]
                if crop is not None:
                    if len(crop) != 4 or not all(type(x) is int for x in crop):
                        raise ValueError('crop is [left, top, right, bottom] in oriented-image pixels')
                    l, t, r, b = crop
                    if not (0 <= l < r <= im.width and 0 <= t < b <= im.height):
                        raise ValueError('crop lies outside the oriented image')
                    box = list(crop)
                    im = im.crop(box)
                im.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                # PNG preserves small diagrams/text better; bounded JPEG is a fallback for photos.
                if im.mode not in ('RGB', 'RGBA', 'L'):
                    im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
                encoded = BytesIO()
                im.save(encoded, format='PNG')
                mime = 'image/png'
                if len(encoded.getvalue()) > policy.max_image_bytes:
                    im = im.convert('RGB')
                    encoded = BytesIO()
                    im.save(encoded, format='JPEG', quality=85)
                    mime = 'image/jpeg'
                if len(encoded.getvalue()) > policy.max_image_bytes:
                    raise Fault('IMAGE_RESPONSE_TOO_LARGE', '图像响应超过传输预算。',
                                str(len(encoded.getvalue())), '降低 max_edge 或分区域 crop。')
                meta = {'ok': True, 'source': name, 'original_sha256': digest(data),
                        'raw_size': list(raw_size), 'exif_orientation': orientation,
                        'oriented_size': list(oriented_size), 'crop_oriented_pixels': box,
                        'preview_size': list(im.size), 'original_modified': False,
                        'coordinate_space': 'EXIF-oriented original',
                        'scale_preview_to_crop': [(box[2]-box[0])/im.width, (box[3]-box[1])/im.height]}
                return {'content': [text_content(meta), {'type': 'image', 'mimeType': mime,
                    'data': base64.b64encode(encoded.getvalue()).decode('ascii')}], 'structuredContent': meta, 'isError': False}
    except Fault:
        raise
    except (OSError, ValueError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise Fault('INVALID_IMAGE', '图像无法安全解码。', type(exc).__name__,
                    '确认图像格式与完整性；HEIC 需要 heif 组件。') from exc


def pdf_page(data, name, policy, page=1, max_edge=1600):
    if not 1 <= page or not 64 <= max_edge <= 4096:
        raise ValueError('page >=1; max_edge between 64 and 4096')
    try:
        import pypdfium2 as pdfium
    except ImportError:
        need('pypdfium2', 'media')
    try:
        with pdfium.PdfDocument(data) as doc:
            if page > len(doc):
                raise ValueError(f'page exceeds {len(doc)}')
            pg = doc[page-1]
            try:
                w, h = pg.get_size()
                bitmap = pg.render(scale=max_edge/max(w, h))
                try:
                    out = BytesIO()
                    bitmap.to_pil().save(out, format='PNG')
                finally:
                    bitmap.close()
            finally:
                pg.close()
            result = image_content(out.getvalue(), f'{name}#page={page}', policy, max_edge=max_edge)
            result['structuredContent'].update({'pdf_sha256': digest(data), 'page': page, 'total_pages': len(doc)})
            result['content'][0] = text_content(result['structuredContent'])
            return result
    except (ValueError, Fault):
        raise
    except Exception as exc:
        raise Fault('PDF_RENDER_FAILED', 'PDF 页面渲染失败。', type(exc).__name__,
                    '检查是否加密、损坏或缺少 media 依赖；不自动尝试密码或 OCR。') from exc


def document_text(data, name, policy, start_page=1, end_page=None):
    if not name.lower().endswith('.pdf'):
        raise Fault('FORMAT_NEEDS_ADAPTER', '此格式没有内置文本解析器。',
                    '当前文档解析器支持 PDF；ZIP 内文本和图像可直接读取。',
                    '使用 read_binary 传递原始字节，或在本机用专用适配器导出文本/预览。', format=name.rsplit('.', 1)[-1])
    try:
        import pypdfium2 as pdfium
    except ImportError:
        need('pypdfium2', 'media')
    pieces = []
    with pdfium.PdfDocument(data) as doc:
        end = min(end_page if end_page is not None else start_page + 9, len(doc))
        if not (1 <= start_page <= end <= len(doc)) or end - start_page >= 10:
            raise ValueError('read at most 10 valid pages at a time, starting at 1')
        for number in range(start_page, end+1):
            page = doc[number-1]
            try:
                textpage = page.get_textpage()
                try:
                    pieces.append(f'[Page {number}]\n' + textpage.get_text_range())
                finally:
                    textpage.close()
            finally:
                page.close()
        text = '\n\n'.join(pieces)
        out = text.encode('utf-8')[:policy.max_text_output_bytes].decode('utf-8', 'ignore')
        return {'ok': True, 'path': name, 'sha256': digest(data), 'content': out,
                'start_page': start_page, 'end_page': end, 'total_pages': len(doc),
                'next_page': end+1 if end < len(doc) else None, 'truncated': len(out) != len(text),
                'visual_review_required': True,
                'note': '提取的文字不等于页面全部内容；图表或扫描页请调用 render_pdf_page。未执行 OCR。'}


def safe_member(name):
    p = PurePosixPath(name.replace('\\', '/'))
    if p.is_absolute() or '..' in p.parts or not p.parts or ':' in p.parts[0] or '\x00' in name:
        raise Fault('UNSAFE_ARCHIVE_MEMBER', '压缩包成员路径不安全。', '绝对路径或路径穿越。', '重新生成安全 ZIP。')
    return p.as_posix()


def zip_open(data):
    try:
        z = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise Fault('INVALID_ARCHIVE', '不是有效 ZIP 文件。', str(exc), '检查格式与文件完整性。') from exc
    if len(z.infolist()) > 20000:
        z.close()
        raise Fault('ARCHIVE_ENTRY_LIMIT', 'ZIP 成员数量超过上限。', '>20000 entries', '拆分压缩包。')
    return z


def check_member(info, policy):
    name = safe_member(info.filename)
    if stat.S_ISLNK(info.external_attr >> 16):
        raise Fault('ARCHIVE_LINK_DENIED', '不读取压缩包中的符号链接。', name, '使用普通文件成员。')
    ok, why, pat = policy.rule(name)
    if not ok:
        raise Fault('POLICY_DENIED', '压缩包内敏感文件也受黑名单限制。', why, '不要打包凭据文件。', matched_rule=pat)
    if info.flag_bits & 1:
        raise Fault('ARCHIVE_ENCRYPTED', '不自动解密 ZIP。', '成员已加密。', '在本机生成仅包含授权数据的非加密副本。')
    if info.file_size > policy.max_file_size or info.file_size / max(1, info.compress_size) > 200:
        raise Fault('ARCHIVE_BOMB_LIMIT', '解压大小或压缩比超过上限。',
                    '可能为压缩炸弹；读取已停止。', '拆分数据或重新打包。', size=info.file_size)
    return name


def archive_list(data, name, policy, offset=0, limit=200):
    if offset < 0 or not 1 <= limit <= 500:
        raise ValueError('offset >=0; limit 1..500')
    with zip_open(data) as z:
        allowed, skipped = [], 0
        seen = set()
        for info in z.infolist():
            try:
                member = check_member(info, policy)
            except Fault:
                skipped += 1
                continue
            if member in seen:
                raise Fault('DUPLICATE_ARCHIVE_MEMBER', 'ZIP 包含重复成员名。', member, '去除歧义后重新打包。')
            seen.add(member)
            allowed.append({'name': member, 'size': info.file_size, 'directory': info.is_dir()})
        selected = allowed[offset:offset+limit]
        return {'ok': True, 'path': name, 'sha256': digest(data), 'entries': selected,
                'skipped_unsafe_or_denied': skipped, 'total_allowed': len(allowed),
                'next_offset': offset+len(selected) if offset+len(selected) < len(allowed) else None}


def archive_bytes(data, member, policy):
    member = safe_member(member)
    with zip_open(data) as z:
        infos = [i for i in z.infolist() if i.filename.replace('\\', '/') == member]
        if len(infos) != 1:
            raise Fault('ARCHIVE_MEMBER_NOT_UNIQUE', '成员不存在或名称重复。', member, '先 list_archive，使用唯一完整路径。')
        info = infos[0]
        check_member(info, policy)
        with z.open(info) as f:
            body = f.read(policy.max_file_size + 1)
        if len(body) > policy.max_file_size:
            raise Fault('ARCHIVE_BOMB_LIMIT', '实际解压大小超过上限。', member, '拆分压缩包。')
    return body


def archive_read(data, name, member, policy, view='auto', page=1, max_edge=1600):
    member = safe_member(member)
    body = archive_bytes(data, member, policy)
    label = name + '!/' + member
    if view == 'binary':
        return binary_content(body, label, 0, 256*1024, policy, archive=name, member=member)
    ext = member.lower().rsplit('.', 1)[-1]
    if view == 'image' or (view == 'auto' and ext in ('png','jpg','jpeg','webp','gif','bmp','tif','tiff','heic','heif')):
        return image_content(body, label, policy, max_edge=max_edge)
    if ext == 'pdf':
        return pdf_page(body, label, policy, page, max_edge) if view in ('auto','page') else document_text(body, label, policy, page, page)
    if b'\0' in body:
        raise Fault('BINARY_CONTENT', '成员不是文本。', label, '改用 view=binary 或专用预览适配器。')
    try:
        text = body.decode('utf-8')
    except UnicodeError as exc:
        raise Fault('BINARY_CONTENT', '成员不是 UTF-8 文本。', label, '使用 view=binary。') from exc
    limited = text.encode()[:policy.max_text_output_bytes].decode('utf-8','ignore')
    return {'ok': True, 'source': label, 'sha256': digest(body), 'content': limited,
            'truncated': limited != text, 'original_modified': False}


def binary_content(data, name, offset, length, policy, *, archive=None, member=None):
    if not (0 <= offset <= len(data)) or not (1 <= length <= 512*1024):
        raise ValueError('offset must be in file; length 1..524288')
    chunk = data[offset:offset+length]
    next_offset = offset+len(chunk) if offset+len(chunk) < len(data) else None
    if archive is not None:
        uri = 'local-mcp://archive/' + quote(archive, safe='/') + '?member=' + quote(member,safe='') + '&'
    else:
        uri = 'local-mcp://file/' + quote(name, safe='/') + '?'
    uri += f'offset={offset}&length={length}&sha256={digest(data)}'
    meta = {'ok': True, 'source': name, 'sha256': digest(data), 'chunk_sha256': digest(chunk),
            'offset': offset, 'bytes': len(chunk), 'total_bytes': len(data), 'next_offset': next_offset,
            'uri': uri, 'note': 'MCP embedded binary resource; not a sandbox path or a claim of client-side materialization.'}
    return {'content': [text_content(meta), {'type': 'resource', 'resource': {
        'uri': uri, 'mimeType': mimetypes.guess_type(name)[0] or 'application/octet-stream',
        'blob': base64.b64encode(chunk).decode('ascii')}}], 'structuredContent': meta, 'isError': False}


def visual_probe(policy):
    """Random code exists ONLY inside pixels; a correct reply verifies host visual delivery."""
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        need('Pillow', 'media')
    import secrets
    code = ''.join(secrets.choice('23456789ABCDEFGHJKMNPQRSTUVWXYZ') for _ in range(6))
    im = Image.new('RGB', (640, 180), 'white')
    draw = ImageDraw.Draw(im)
    font = ImageFont.load_default(size=60)
    draw.text((35, 55), code, fill='black', font=font)
    data = BytesIO()
    im.save(data, format='PNG')
    result = image_content(data.getvalue(), 'visual-capability-probe', policy, max_edge=640)
    # Never return the answer as text or metadata. No filesystem side effect.
    result['structuredContent'] = {'ok': True, 'test': 'visual delivery',
        'instruction': '请读取图中六位字符；看不到图片就明确报告，不要猜测。',
        'answer_sha256': digest(code.encode('ascii')),
        'note': '图片已由服务生成；只有客户端能真正看到并答对，才通过端到端视觉验收。'}
    result['content'][0] = text_content(result['structuredContent'])
    return result
