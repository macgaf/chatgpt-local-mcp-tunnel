import base64
import json
from io import BytesIO
import zipfile
import pytest
from home_readonly_mcp.errors import Fault
from home_readonly_mcp.storage import digest
from home_readonly_mcp import media


def png_bytes():
    Image=pytest.importorskip('PIL.Image')
    im=Image.new('RGB',(320,180),(20,130,220))
    buf=BytesIO();im.save(buf,format='PNG')
    return buf.getvalue()


def pdf_bytes():
    # Tiny deterministic PDF fixture: one text line and one diagram rectangle.
    stream=b'BT /F1 22 Tf 40 730 Td (MCP PDF fixture) Tj ET\n0 0 1 RG 40 600 120 60 re S\n'
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
        b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'endstream']
    out=b'%PDF-1.4\n';offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(out));out+=str(i).encode()+b' 0 obj\n'+obj+b'\nendobj\n'
    xref=len(out);out+=b'xref\n0 6\n0000000000 65535 f \n'
    for off in offsets[1:]:out+=f'{off:010d} 00000 n \n'.encode()
    out+=f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode()
    return out


def zip_bytes(items,compression=zipfile.ZIP_STORED):
    b=BytesIO()
    with zipfile.ZipFile(b,'w',compression=compression) as z:
        for name,body in items:z.writestr(name,body)
    return b.getvalue()


def decoded_image(result):
    Image=pytest.importorskip('PIL.Image')
    item=next(x for x in result['content'] if x['type']=='image')
    assert item['mimeType'] in ('image/png','image/jpeg')
    with Image.open(BytesIO(base64.b64decode(item['data']))) as im:
        return im.size


def test_image_not_text_json(space):
    svc=space[3];body=png_bytes();(space[1]/'plot.png').write_bytes(body)
    r=svc.read_image('plot.png',max_edge=160)
    assert decoded_image(r)==(160,90)
    assert r['structuredContent']['original_sha256']==digest(body)
    assert (space[1]/'plot.png').read_bytes()==body


def test_exif_and_crop(space):
    Image=pytest.importorskip('PIL.Image')
    im=Image.new('RGB',(100,50));exif=im.getexif();exif[274]=6
    b=BytesIO();im.save(b,format='JPEG',exif=exif)
    (space[1]/'rot.jpg').write_bytes(b.getvalue())
    r=space[3].read_image('rot.jpg',max_edge=64,crop=[0,0,50,100])
    assert r['structuredContent']['oriented_size']==[50,100]
    assert decoded_image(r)==(32,64)
    assert r['structuredContent']['scale_preview_to_crop']==[1.5625,1.5625]


def test_image_safety(space):
    pytest.importorskip('PIL.Image')
    (space[1]/'bad.png').write_bytes(b'not image')
    with pytest.raises(Fault) as got:space[3].read_image('bad.png')
    assert got.value.code=='INVALID_IMAGE'
    (space[1]/'plot.png').write_bytes(png_bytes())
    space[2].max_image_pixels=10
    with pytest.raises(Fault):space[3].read_image('plot.png')


def test_visual_probe_does_not_include_answer(space):
    pytest.importorskip('PIL.Image')
    r=space[3].visual_probe()
    assert decoded_image(r)==(640,180)
    assert len(r['structuredContent']['answer_sha256'])==64
    assert 'answer' not in r['structuredContent']


def test_pdf_text_and_actual_render(space):
    pytest.importorskip('pypdfium2');pytest.importorskip('PIL.Image')
    (space[1]/'test.pdf').write_bytes(pdf_bytes())
    text=space[3].read_document('test.pdf')
    assert 'MCP PDF fixture' in text['content'] and text['visual_review_required']
    rendered=space[3].render_pdf_page('test.pdf')
    assert max(decoded_image(rendered))==1600
    assert rendered['structuredContent']['page']==1
    assert (space[1]/'test.pdf').read_bytes()==pdf_bytes()


def test_unsupported_format_explains(space):
    (space[1]/'model.blend').write_bytes(b'BLENDER-v300')
    with pytest.raises(Fault) as got:space[3].read_document('model.blend')
    assert got.value.code=='FORMAT_NEEDS_ADAPTER'


def test_zip_images_text_pdf_and_filtering(space):
    pytest.importorskip('pypdfium2')
    archive=zip_bytes([('pics/1.png',png_bytes()),('report.pdf',pdf_bytes()),('README.txt','中文'),
        ('../escape','bad'),('.env','secret'),('.ssh/key','private')])
    (space[1]/'data.zip').write_bytes(archive)
    svc=space[3]
    listing=svc.list_archive('data.zip')
    assert listing['skipped_unsafe_or_denied']==3
    assert decoded_image(svc.read_archive_member('data.zip','pics/1.png'))==(320,180)
    assert svc.read_archive_member('data.zip','README.txt')['content']=='中文'
    assert max(decoded_image(svc.read_archive_member('data.zip','report.pdf')))==1600
    assert not (space[1]/'pics').exists()
    with pytest.raises(Fault):svc.read_archive_member('data.zip','.env')
    assert (space[1]/'data.zip').read_bytes()==archive


def test_binary_chunks_and_stale_read(space):
    body=bytes(range(256))*3000
    (space[1]/'model.bin').write_bytes(body)
    svc=space[3];offset=0;out=b''
    while True:
        result=svc.read_binary('model.bin',offset,131072,digest(body))
        m=result['structuredContent'];chunk=base64.b64decode(result['content'][1]['resource']['blob'])
        assert digest(chunk)==m['chunk_sha256']
        assert svc.read_resource(m['uri'])['content'][1]['resource']['blob']==base64.b64encode(chunk).decode()
        out+=chunk
        if m['next_offset'] is None:break
        offset=m['next_offset']
    assert out==body
    (space[1]/'model.bin').write_bytes(b'changed')
    with pytest.raises(Fault) as got:svc.read_resource(result['structuredContent']['uri'])
    assert got.value.code=='HASH_CONFLICT'


def test_archive_binary_resource_roundtrip(space):
    body=bytes(range(256))*2500
    (space[1]/'binary.zip').write_bytes(zip_bytes([('model.bin',body),('empty.bin',b''),('one.pdf',pdf_bytes())]))
    svc=space[3];result=svc.read_archive_member('binary.zip','model.bin',view='binary')
    uri=result['structuredContent']['uri']
    assert uri.startswith('local-mcp://archive/')
    offset=0;out=b''
    while True:
        import re
        result=svc.read_resource(re.sub(r'offset=\d+',f'offset={offset}',uri))
        out+=base64.b64decode(result['content'][1]['resource']['blob'])
        offset=result['structuredContent']['next_offset']
        if offset is None:break
    assert out==body
    assert svc.read_archive_member('binary.zip','empty.bin',view='binary')['structuredContent']['bytes']==0
    assert svc.read_archive_member('binary.zip','one.pdf',view='binary')['content'][1]['type']=='resource'

@pytest.mark.parametrize('name',['../out','/absolute','C:/absolute','good/../../out','..\\outside'])
def test_archive_path_traversal(space,name):
    (space[1]/'bad.zip').write_bytes(zip_bytes([(name,'bad')]))
    assert space[3].list_archive('bad.zip')['entries']==[]
    with pytest.raises(Fault):space[3].read_archive_member('bad.zip',name)


def test_zip_bomb_and_duplicate(space):
    (space[1]/'bomb.zip').write_bytes(zip_bytes([('large.txt',b'0'*1000000)],zipfile.ZIP_DEFLATED))
    with pytest.raises(Fault) as got:space[3].read_archive_member('bomb.zip','large.txt')
    assert got.value.code=='ARCHIVE_BOMB_LIMIT'
    with pytest.warns(UserWarning):body=zip_bytes([('dup','a'),('dup','b')])
    (space[1]/'dup.zip').write_bytes(body)
    with pytest.raises(Fault):space[3].read_archive_member('dup.zip','dup')
