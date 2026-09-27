from __future__ import annotations
import base64
import difflib
import fnmatch
import json
import os
from pathlib import Path
import time
import uuid
from .errors import Fault, normalize_error
from .capabilities import capability_summary
from .storage import Lease, commit_bytes, digest, parent_handle, read_bytes, expected_matches
from . import media


from .command_tools import CommandManager, CommandMixin
from .git_tools import GitTools, GitMixin
from .search_tools import SearchMixin
from .patches import apply_changes
from .file_actions import FileActions
from .codex_history import CodexHistoryMixin
from .eventlog import EventLog


class HomeService(SearchMixin, GitMixin, CommandMixin, FileActions, CodexHistoryMixin):
    def __init__(self, policy):
        self.policy = policy
        self.runtime_instance = uuid.uuid4().hex
        self.audit = EventLog(policy.config_path, state_dir=policy.state_dir)
        self.commands = CommandManager(policy, audit=self.audit)
        self.git = GitTools(self)

    def close(self):
        self.commands.close()

    def visual_probe(self):
        return media.visual_probe(self.policy)

    def read_resource(self, uri):
        from urllib.parse import parse_qs, unquote, urlparse
        parsed = urlparse(uri)
        if parsed.scheme != 'local-mcp' or parsed.netloc not in ('file','archive'):
            raise ValueError('unsupported resource URI')
        path = unquote(parsed.path.lstrip('/'))
        query = parse_qs(parsed.query)
        offset = int(query.get('offset', ['0'])[0])
        length = int(query.get('length', ['262144'])[0])
        expected = query.get('sha256',[None])[0]
        if parsed.netloc=='archive':
            member = query.get('member',[''])[0]
            body = media.archive_bytes(read_bytes(self.policy,path)[1],member,self.policy)
            expected_matches(body,expected or digest(body))
            return media.binary_content(body,path+'!/'+member,offset,length,self.policy,archive=path,member=member)
        return self.read_binary(path,offset,length,expected)

    def policy_info(self):
        return {'ok': True, **self.policy.summary(), 'capabilities': capability_summary(self)}

    def file_info(self, path):
        p = self.policy.require(path)
        st = p.stat()
        out = {'ok': True, 'path': self.policy.relative(p), 'size': st.st_size,
               'mtime_ns': st.st_mtime_ns, 'type': 'directory' if p.is_dir() else 'file'}
        if p.is_file() and st.st_size <= self.policy.max_file_size:
            out['sha256'] = digest(read_bytes(self.policy, path)[1])
        return out

    def list_directory(self, path='.', offset=0, limit=200):
        if offset < 0 or not 1 <= limit <= self.policy.max_directory_entries:
            raise ValueError('invalid offset/limit')
        p = self.policy.require(path)
        if not p.is_dir():
            raise ValueError('path must be a directory')
        allowed, blocked, scanned = [], 0, 0
        with os.scandir(p) as entries:
            for entry in entries:
                scanned += 1
                if scanned > self.policy.max_search_files:
                    break
                try:
                    child = self.policy.require(entry.path)
                    st = child.stat()
                except (OSError, Fault):
                    blocked += 1
                    continue
                allowed.append({'name': entry.name, 'path': self.policy.relative(child),
                    'type': 'directory' if child.is_dir() else 'file', 'size': st.st_size,
                    'mtime_ns': st.st_mtime_ns, 'symlink': entry.is_symlink()})
        allowed.sort(key=lambda x: x['name'].casefold())
        selected = allowed[offset:offset+limit]
        return {'ok': True, 'path': self.policy.relative(p), 'entries': selected, 'blocked': blocked,
                'next_offset': offset+len(selected) if offset+len(selected) < len(allowed) else None,
                'scan_truncated': scanned > self.policy.max_search_files,
                'note': '分页不是快照；目录变化时请重新列出。'}

    def read_file(self, path, start_line=1, end_line=None):
        p, data, st = read_bytes(self.policy, path)
        if b'\0' in data:
            raise Fault('BINARY_CONTENT', '此文件不是文本。', path,
                        '图像请 read_image，PDF 请 read_document/render_pdf_page，其他格式请 read_binary。')
        text = data.decode('utf-8')
        lines = text.splitlines(keepends=True)
        if start_line < 1 or (end_line is not None and end_line < start_line):
            raise ValueError('line range is 1-based, end_line >= start_line')
        end = min(end_line or len(lines), len(lines))
        selected = ''.join(lines[start_line-1:end])
        content = selected.encode()[:self.policy.max_text_output_bytes].decode('utf-8', 'ignore')
        return {'ok': True, 'path': self.policy.relative(p), 'content': content,
                'sha256': digest(data), 'size': len(data), 'mtime_ns': st.st_mtime_ns,
                'start_line': start_line, 'end_line': start_line + len(content.splitlines())-1,
                'total_lines': len(lines), 'truncated': content != selected,
                'next_line': end+1 if end < len(lines) and content == selected else None,
                'partial_last_line': content != selected and not content.endswith('\n'),
                'truncation_action': '缩小行范围；超长单行可用 read_binary 按字节分块读取。' if content != selected else None}

    def _walk(self, path):
        base = self.policy.require(path)
        if not base.is_dir():
            raise ValueError('search path must be a directory')
        seen, deadline = 0, time.monotonic()+10
        for root, dirs, files in os.walk(base, followlinks=False):
            dirs.sort()
            retained = []
            for name in dirs:
                p = Path(root) / name
                seen += 1
                if seen > self.policy.max_search_files or time.monotonic() > deadline:
                    yield None
                    return
                try:
                    self.policy.require(str(p))
                    if not p.is_symlink():
                        retained.append(name)
                except (Fault, OSError):
                    continue
            dirs[:] = retained
            for name in sorted(files):
                seen += 1
                if seen > self.policy.max_search_files or time.monotonic() > deadline:
                    yield None
                    return
                p = Path(root) / name
                try:
                    p = self.policy.require(str(p))
                    if p.is_file():
                        yield p
                except (Fault, OSError):
                    continue

    def find_files(self, pattern, path='.', max_results=100):
        if not 1 <= max_results <= self.policy.max_search_results or not pattern:
            raise ValueError('invalid max_results/pattern')
        results, truncated = [], False
        for p in self._walk(path):
            if p is None:
                truncated = True
                break
            rel = self.policy.relative(p)
            if fnmatch.fnmatchcase(rel, pattern) or fnmatch.fnmatchcase(p.name, pattern):
                results.append(rel)
                if len(results) >= max_results:
                    truncated = True
                    break
        return {'ok': True, 'results': results, 'truncated': truncated,
                'note': '达到数量/时间/遍历预算时不代表扫描完整；缩小 path 继续。'}

    def search_text(self, query, path='.', glob='*', max_results=100, case_sensitive=False):
        if not query or not 1 <= max_results <= self.policy.max_search_results:
            raise ValueError('query is required; invalid max_results')
        needle = query if case_sensitive else query.casefold()
        results, truncated, skipped = [], False, 0
        for p in self._walk(path):
            if p is None:
                truncated = True
                break
            rel = self.policy.relative(p)
            if not (fnmatch.fnmatchcase(rel, glob) or fnmatch.fnmatchcase(p.name, glob)):
                continue
            try:
                data = read_bytes(self.policy, str(p))[1]
                if b'\0' in data:
                    skipped += 1
                    continue
                text = data.decode('utf-8')
            except (OSError, Fault, UnicodeError):
                skipped += 1
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if needle in (line if case_sensitive else line.casefold()):
                    results.append({'path': rel, 'line': i, 'text': line[:1000]})
                    if len(results) >= max_results:
                        truncated = True
                        break
            if truncated:
                break
        return {'ok': True, 'results': results, 'truncated': truncated, 'skipped_files': skipped}

    def write_file(self, path, content, expected_sha256=None, dry_run=False, append=False):
        if type(append) is not bool:
            raise ValueError('append must be boolean')
        return self._write(path, content.encode('utf-8'), expected_sha256, dry_run, append=append)

    def write_binary(self, path, data_base64, expected_sha256=None, dry_run=False):
        if len(data_base64) > (self.policy.max_file_size*4//3)+8:
            raise ValueError('base64 payload exceeds configured file size')
        return self._write(path, base64.b64decode(data_base64, validate=True), expected_sha256, dry_run)

    def _write(self, path, data, expected, dry_run, append=False):
        p = self.policy.require(path, write=True, must_exist=False)
        self.commands.guard_mutation([p])
        with Lease(self.policy.state_dir, p, 'write_file'):
            old = read_bytes(self.policy, str(p))[1] if p.exists() else None
            if append and old is not None:
                old.decode('utf-8')
                data = old + data
            return commit_bytes(self.policy, p, data, old, expected, dry_run=dry_run)

    def edit_file(self, path, old_text, new_text, expected_sha256, dry_run=False):
        return self.apply_patch(path, [{'old_text': old_text, 'new_text': new_text}], expected_sha256, dry_run)

    def apply_patch(self, path=None, edits=None, expected_sha256=None, dry_run=False, changes=None):
        """Legacy single-file form or cross-file changes; exactly one form per call."""
        if changes is not None:
            if path is not None or edits is not None or expected_sha256 is not None:
                raise ValueError('changes cannot be combined with legacy path/edits/expected_sha256')
            return apply_changes(self,changes,dry_run)
        if path is None or edits is None:
            raise ValueError('provide changes or legacy path and edits')
        original_changes=[{'path':path, **e, 'expected_sha256':expected_sha256} for e in edits]
        result=apply_changes(self,original_changes,dry_run)
        if dry_run:
            return {'ok':True,'dry_run':True,**result['files'][0]}
        return result['files'][0]

    def create_directory(self, path):
        p = self.policy.require(path, write=True, must_exist=False)
        self.commands.guard_mutation([p])
        with Lease(self.policy.state_dir, p, 'create_directory'):
            if p.is_dir():
                return {'ok': True, 'created': False, 'path': self.policy.relative(p)}
            with parent_handle(self.policy, p) as parent:
                os.mkdir(p if parent is None else p.name, mode=0o700,
                         **({} if parent is None else {'dir_fd': parent}))
        return {'ok': True, 'created': True, 'path': self.policy.relative(p)}

    def list_backups(self, path):
        p = self.policy.require(path, must_exist=False)
        base = self.policy.state_dir / 'backups'
        found = []
        if base.exists():
            for meta in base.glob('*.json'):
                data = json.loads(meta.read_text())
                if data.get('path') == str(p) and data.get('root') == str(self.policy.root):
                    found.append({k: data[k] for k in ('id','sha256','created_at','size')})
        found.sort(key=lambda x: x['created_at'], reverse=True)
        return {'ok': True, 'backups': found[:100], 'truncated': len(found) > 100}

    def restore_file(self, path, backup_id, expected_sha256, dry_run=False):
        p = self.policy.require(path, write=True, must_exist=False)
        if len(backup_id) != 32 or any(c not in '0123456789abcdef' for c in backup_id):
            raise ValueError('invalid backup id')
        base = self.policy.state_dir / 'backups'
        meta = json.loads((base / (backup_id+'.json')).read_text())
        if meta.get('path') != str(p) or meta.get('root') != str(self.policy.root):
            raise Fault('BACKUP_SCOPE_MISMATCH', '备份不属于该文件/root。', backup_id, '使用 list_backups 返回的对应备份。')
        with (base / (backup_id+'.bin')).open('rb') as f:
            data = f.read(self.policy.max_file_size+1)
        if digest(data) != meta['sha256']:
            raise Fault('BACKUP_CORRUPT', '备份哈希不匹配。', backup_id, '停止恢复，检查本机备份存储。')
        return self._write(path, data, expected_sha256, dry_run)

    def read_image(self, path, max_edge=1600, crop=None):
        p, data, _ = read_bytes(self.policy, path)
        return media.image_content(data, self.policy.relative(p), self.policy, max_edge=max_edge, crop=crop)

    def render_pdf_page(self, path, page=1, max_edge=1600):
        p, data, _ = read_bytes(self.policy, path)
        return media.pdf_page(data, self.policy.relative(p), self.policy, page, max_edge)

    def read_document(self, path, start_page=1, end_page=None):
        p, data, _ = read_bytes(self.policy, path)
        return media.document_text(data, self.policy.relative(p), self.policy, start_page, end_page)

    def list_archive(self, path, offset=0, limit=200):
        p, data, _ = read_bytes(self.policy, path)
        return media.archive_list(data, self.policy.relative(p), self.policy, offset, limit)

    def read_archive_member(self, path, member, view='auto', page=1, max_edge=1600):
        p, data, _ = read_bytes(self.policy, path)
        return media.archive_read(data, self.policy.relative(p), member, self.policy, view, page, max_edge)

    def read_binary(self, path, offset=0, length=262144, expected_sha256=None):
        p, data, _ = read_bytes(self.policy, path)
        expected_matches(data, expected_sha256 or digest(data))
        return media.binary_content(data, self.policy.relative(p), offset, length, self.policy)

    def diagnose(self, path=None):
        result = {'ok': True, 'mode': self.policy.mode, 'root': str(self.policy.root),
                  'capabilities': capability_summary(self),
                  'shell_jobs': {'enabled': self.policy.enable_commands and self.policy.mode == 'read_write', 'active': [j.id for j in self.commands.jobs.values() if not j.done.is_set()], 'gate': 'overlapping workspace only'},
                  'windows_security': 'path checks, not an OS sandbox' if os.name == 'nt' else 'POSIX no-follow directory descriptors'}
        if path is not None:
            p = self.policy.require(path, must_exist=False)
            candidate = p / '.local-mcp-capability-probe' if p.is_dir() else p
            try:
                self.policy.resolve(str(candidate), write=True)
                self.commands.guard_mutation([candidate])
                result['file_write'] = {'allowed': True, 'tested': 'policy_only', 'disk_write_tested': False}
            except (Fault, OSError, ValueError) as exc:
                result['file_write'] = {'allowed': False, 'tested': 'policy_only',
                                        'error': normalize_error(exc).payload()['error']}
            try:
                status = self.git_status(str(p if p.is_dir() else p.parent))
                result['git'] = {'supported': True, 'branch': status['branch'], 'head': status['head'],
                                 'dirty': bool(status['entries'] or status['blocked_entries']),
                                 'state_truncated': status['truncated']}
            except (Fault, OSError, ValueError) as exc:
                result['git'] = {'supported': False, 'error': normalize_error(exc).payload()['error']}
            try:
                with Lease(self.policy.state_dir, p, 'diagnostic_probe'):
                    result['lock'] = {'held': False, 'note': 'stale metadata alone is not a held OS lock'}
            except Fault as exc:
                if exc.code!='FILE_LOCKED':
                    raise
                result['lock'] = {'held': True, **exc.details}
        return result


ReadOnlyHomeService = HomeService  # Backward-compatible import, mode is enforced by Policy.
