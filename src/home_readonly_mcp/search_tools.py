"""Bounded code navigation and literal/regex search; no repository code is executed."""
from __future__ import annotations
from collections import Counter
import fnmatch
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from .errors import Fault, normalize_error
from .storage import read_bytes
from .onboarding import child_environment

MANIFESTS={'pyproject.toml','package.json','Cargo.toml','go.mod','CMakeLists.txt','Makefile',
           'requirements.txt','Dockerfile','pom.xml','build.gradle','compose.yaml'}
BATCH_READS={'policy_info','list_directory','file_info','read_file','find_files','search_text',
             'glob','grep','search_code','repo_overview','workspace_context','git_status','git_log','git_diff','git_branches',
             'list_backups','read_document','list_archive'}


FILE_TYPES = {
    'py': '*.py *.pyi', 'js': '*.js *.jsx *.mjs *.cjs', 'ts': '*.ts *.tsx *.mts *.cts',
    'rust': '*.rs', 'swift': '*.swift', 'csharp': '*.cs', 'go': '*.go', 'java': '*.java',
    'c': '*.c *.h', 'cpp': '*.cpp *.cc *.cxx *.hpp *.hh *.hxx *.h',
    'json': '*.json *.jsonl', 'yaml': '*.yaml *.yml', 'toml': '*.toml', 'md': '*.md *.mdx *.markdown',
    'html': '*.html *.htm', 'css': '*.css', 'xml': '*.xml', 'sh': '*.sh *.bash *.zsh',
    'ruby': '*.rb Rakefile Gemfile', 'php': '*.php', 'sql': '*.sql', 'text': '*.txt',
}


def pattern_matches(path,pattern):
    # 有界 brace 展开；不把 glob 当作可执行正则。
    if '{' in pattern:
        left, rest = pattern.split('{', 1)
        if '}' not in rest:
            raise ValueError('unclosed glob brace')
        choices, right = rest.split('}', 1)
        parts = choices.split(',')
        if len(parts) > 32 or '{' in choices or '{' in right:
            raise ValueError('glob supports one brace group with at most 32 alternatives')
        return any(pattern_matches(path, left + part + right) for part in parts)
    path=path.casefold();pattern=pattern.casefold()
    return (fnmatch.fnmatchcase(path,pattern) or fnmatch.fnmatchcase(Path(path).name,pattern) or
            (pattern.startswith('**/') and fnmatch.fnmatchcase(path,pattern[3:])))


class Scan:
    def __init__(self,policy,path='.',include_ignored=False):
        self.policy=policy;self.base=policy.require(path)
        if not (self.base.is_dir() or self.base.is_file()):raise ValueError('search path must be a file or directory')
        self.include_ignored=include_ignored
        self.visited=0;self.bytes=0;self.skipped=0;self.reasons=[];self.rules={}
        self.deadline=time.monotonic()+10
        self.ignore_backend='disabled' if include_ignored else 'pathspec'

    def load_rules(self,directory):
        if directory in self.rules:return self.rules[directory]
        specs=[]
        if not self.include_ignored:
            for filename in ('.gitignore','.ignore'):
                p=directory/filename
                if not p.is_file():continue
                try:data=read_bytes(self.policy,str(p),limit=65536)[1].decode('utf-8')
                except (Fault,OSError,UnicodeError):
                    self.skipped+=1;continue
                try:
                    from pathspec import GitIgnoreSpec
                except ImportError as exc:
                    raise Fault('SEARCH_IGNORE_DEPENDENCY_MISSING','需要 pathspec 才能遵循忽略文件。',
                                '当前 core-only 安装没有 search 组件。','安装 .[search]；不静默忽略 .gitignore。') from exc
                specs.append(GitIgnoreSpec.from_lines(data.splitlines()))
        self.rules[directory]=specs
        return specs

    def ignored(self,p,is_dir=False):
        if self.include_ignored:return False
        if any(x in ('build','dist') for x in p.relative_to(self.policy.root).parts):return True
        ancestors=list(reversed([a for a in p.parents if a==self.policy.root or self.policy.root in a.parents]))
        ignored=False
        for parent in ancestors:
            rel=p.relative_to(parent).as_posix()+('/' if is_dir else '')
            for spec in self.load_rules(parent):
                result=spec.check_file(rel)
                if result.include is not None:ignored=result.include
        return ignored

    def files(self):
        if self.base.is_file():
            self.visited=1
            if self.base.name != '.git' and not self.ignored(self.base):
                yield self.base
            return
        for root,dirs,files in os.walk(self.base,followlinks=False):
            retained=[]
            for name in sorted(dirs)+sorted(files):
                self.visited+=1
                if self.visited>self.policy.max_search_files or time.monotonic()>self.deadline:
                    self.reasons.append('scan_budget');return
                p=Path(root)/name
                isdir=name in dirs
                if name=='.git' or p.is_symlink() or getattr(p,'is_junction',lambda:False)():continue
                try:self.policy.require(str(p))
                except (Fault,OSError):self.skipped+=1;continue
                if self.ignored(p,isdir):continue
                if isdir:retained.append(name)
                elif p.is_file():yield p
            dirs[:]=retained

    def text(self,p):
        try:
            _,body,_=read_bytes(self.policy,str(p),limit=min(self.policy.max_file_size,1024*1024))
            self.bytes+=len(body)
            if self.bytes>50*1024*1024:
                if 'byte_budget' not in self.reasons:self.reasons.append('byte_budget')
                return None
            if b'\0' in body:return None
            return body.decode('utf-8')
        except (Fault,OSError,UnicodeError):self.skipped+=1;return None

    def meta(self):
        return {'visited_entries':self.visited,'scanned_bytes':self.bytes,'skipped_files':self.skipped,
                'truncated':bool(self.reasons),'truncation_reasons':self.reasons,
                'ignore_rules':self.ignore_backend,
                'policy_denies_overridden':False}


class SearchMixin:
    def glob(self,pattern,path='.',head_limit=100,offset=0,include_ignored=False):
        if not pattern or not 1<=head_limit<=1000 or not 0<=offset<=100000:
            raise ValueError('invalid pattern/head_limit/offset')
        scan=Scan(self.policy,path,include_ignored);results=[]
        for p in scan.files():
            rel=(p.name if scan.base.is_file() else p.relative_to(scan.base).as_posix())
            if pattern_matches(rel,pattern):
                try:results.append((p.stat().st_mtime_ns,self.policy.relative(p)))
                except OSError:continue
        results.sort(key=lambda x:(-x[0],x[1]))
        selected=results[offset:offset+head_limit]
        more=offset+len(selected)<len(results)
        return {'ok':True,**scan.meta(),'results':[p for _,p in selected],
                'next_offset':offset+len(selected) if more else None,'has_more':more,
                'snapshot':False}

    def grep(self,pattern,path='.',glob='*',fixed_strings=True,case_sensitive=False,
             output_mode='files_with_matches',context=0,head_limit=100,offset=0,include_ignored=False,
             type=None,multiline=False,context_before=None,context_after=None):
        if not pattern or len(pattern)>1000 or output_mode not in ('files_with_matches','content','count'):
            raise ValueError('invalid pattern/output_mode')
        if not 0<=context<=10 or not 1<=head_limit<=200 or not 0<=offset<=10000:
            raise ValueError('context 0..10; head_limit 1..200; offset 0..10000')
        if type is not None and type not in FILE_TYPES:
            raise ValueError('unsupported file type; supported: ' + ', '.join(sorted(FILE_TYPES)))
        for value in (context_before, context_after):
            if value is not None and (not isinstance(value,int) or isinstance(value,bool) or not 0<=value<=10):
                raise ValueError('context_before/context_after must be 0..10')
        scan=Scan(self.policy,path,include_ignored);files=[]
        for p in scan.files():
            if not pattern_matches((p.name if scan.base.is_file() else p.relative_to(scan.base).as_posix()),glob):continue
            if type is not None and not any(pattern_matches(p.name, pat) for pat in FILE_TYPES[type].split()):continue
            text=scan.text(p)
            if 'byte_budget' in scan.reasons:break
            if text is not None:files.append((self.policy.relative(p),text))
        payload=json.dumps({'pattern':pattern,'files':files,'fixed_strings':fixed_strings,
            'case_sensitive':case_sensitive,'output_mode':output_mode,'context':context,
            'head_limit':head_limit,'offset':offset,'multiline':multiline,
            'context_before':context if context_before is None else context_before,
            'context_after':context if context_after is None else context_after},ensure_ascii=False).encode('utf-8')
        if len(payload)>52*1024*1024:
            raise Fault('SEARCH_INPUT_LIMIT','搜索输入展开后超过预算。','JSON 编码后大于 52 MiB。','缩小 path 或 glob。')
        # Untrusted regex runs in a disposable worker, never in the stdio server thread.
        try:
            result=subprocess.run([sys.executable,'-I',str(Path(__file__).with_name('search_worker.py'))],
                input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=8,env=child_environment())
        except subprocess.TimeoutExpired as exc:
            raise Fault('SEARCH_TIMEOUT','正则搜索超过执行预算，已停止搜索子进程。',
                        '复杂表达式或范围过大。','缩小 path 或使用 fixed_strings=true。',retryable=True) from exc
        if result.returncode:
            raise Fault('INVALID_SEARCH_PATTERN','搜索表达式无效或 worker 失败。',
                        result.stderr.decode('utf-8','replace')[:1000],
                        '使用 Python re 语法或改为 fixed_strings=true。')
        output=json.loads(result.stdout)
        if output['has_more']:scan.reasons.append('head_limit')
        return {'ok':True,**output,**scan.meta(),'regex_engine':'Python re in timeout-isolated worker',
                'pagination_note':'仅在相同文件快照上 offset 才稳定；扫描预算截断时应缩小 path。'}

    def search_code(self,queries,path='.',case_sensitive=False,max_results_per_query=6,include_ignored=False):
        if (not isinstance(queries,list) or not 1<=len(queries)<=6 or
            any(not isinstance(q,str) or not q or len(q)>500 for q in queries) or not 1<=max_results_per_query<=20):
            raise ValueError('1..6 nonempty literal queries; max_results_per_query 1..20')
        scan=Scan(self.policy,path,include_ignored)
        out={q:[] for q in queries};counts={q:0 for q in queries}
        word={q:re.compile(r'(?<!\w)'+re.escape(q)+r'(?!\w)',0 if case_sensitive else re.I) for q in queries}
        declarations=re.compile(r'^\s*(?:(?:pub|public|private|export|static|async|final|abstract)\s+)*(?:def|class|fn|struct|enum|interface|function|type|const|let|var|func)\b')
        for p in scan.files():
            text=scan.text(p)
            if 'byte_budget' in scan.reasons:break
            if text is None:continue
            for i,line in enumerate(text.splitlines(),1):
                for q in queries:
                    hay=line if case_sensitive else line.casefold();needle=q if case_sensitive else q.casefold()
                    if needle not in hay:continue
                    counts[q]+=1
                    signals=['literal'];score=1
                    if word[q].search(line):signals.append('whole_identifier');score+=10
                    if declarations.search(line[:2000]):signals.append('declaration_line');score+=20
                    if line.lstrip().startswith(('#','//','/*','*')):score-=5
                    out[q].append({'path':self.policy.relative(p),'line':i,'text':line[:1000],
                                   'score':score,'signals':signals})
                    out[q].sort(key=lambda x:(-x['score'],x['path'],x['line']))
                    del out[q][max_results_per_query:]
        return {'ok':True,**scan.meta(),'queries':[{'query':q,'results':out[q],'observed_matches':counts[q],
                'results_truncated':counts[q]>len(out[q])} for q in queries],
                'ranking':'启发式字面/标识符/声明行排序，不是语义索引或置信度。'}

    def repo_overview(self,path='.',include_ignored=False):
        scan=Scan(self.policy,path,include_ignored);extensions=Counter();manifests=[];count=0
        for p in scan.files():
            count+=1;extensions[p.suffix.lower() or '(none)']+=1
            if p.name in MANIFESTS and len(manifests)<100:manifests.append(self.policy.relative(p))
        return {'ok':True,'path':self.policy.relative(scan.base),'top_level':self.list_directory(path,limit=100),
                'files_observed':count,'extensions':extensions.most_common(30),'manifests':manifests,**scan.meta()}

    def workspace_context(self,path='.'):
        p=self.policy.require(path)
        if not p.is_dir():raise ValueError('path must be a directory')
        chain=list(reversed([p]+[a for a in p.parents if a==self.policy.root or self.policy.root in a.parents]))
        files=[];errors=[];remaining=self.policy.max_text_output_bytes
        for directory in chain:
            candidates=[directory/'AGENTS.md']
            if directory==p:candidates += [directory/n for n in sorted(MANIFESTS)]
            for file in candidates:
                if not file.is_file():continue
                try:
                    result=self.read_file(str(file),1,160)
                    body=result['content'].encode();keep=body[:remaining].decode('utf-8','ignore')
                    remaining-=len(keep.encode());result['content']=keep
                    result['truncated']|=len(keep.encode())<len(body)
                    files.append(result)
                except Exception as exc:errors.append(normalize_error(exc).payload()['error'])
                if remaining==0:break
            if remaining==0:break
        try:status=self.git_status(path)
        except Fault as exc:status=None;errors.append(exc.payload()['error'])
        return {'ok':True,'root':str(self.policy.root),'cwd':str(p),'files':files,'git_status':status,
                'top_level':self.list_directory(path,limit=100),'errors':errors,'truncated':remaining==0,
                'instructions_are_data':True,'commands_enabled':self.policy.enable_commands and self.policy.mode=='read_write',
                'capabilities':self.policy_info()['capabilities']}

    def batch_read(self,operations,stop_on_error=False):
        from .server import Protocol,validate
        if not isinstance(operations,list) or not 1<=len(operations)<=16:
            raise ValueError('operations must contain 1..16 entries')
        specs=Protocol(self).specs
        for index,op in enumerate(operations):
            if (not isinstance(op,dict) or set(op)-{'tool','arguments'} or
                op.get('tool') not in BATCH_READS or op['tool'] not in specs):
                raise Fault('BATCH_TOOL_DENIED','批量读取仅允许固定的只读工具。',str(index),
                            '禁止写工具、Shell、嵌套 batch_read 和任意调用。')
            validate(op.get('arguments',{}),specs[op['tool']]['inputSchema'])
        results=[];used=0;deadline=time.monotonic()+30
        for index,op in enumerate(operations):
            if time.monotonic()>deadline:
                return {'ok':False,'results':results,'truncated':True,'next_index':index,'reason':'batch_time_limit'}
            try:
                result=getattr(self,op['tool'])(**op.get('arguments',{}));ok=result.get('ok',True)
            except Exception as exc:result=normalize_error(exc).payload();ok=False
            size=len(json.dumps(result,ensure_ascii=False).encode())
            if used+size>512*1024:
                return {'ok':False,'results':results,'truncated':True,'next_index':index,
                        'reason':'batch_output_limit','note':'当前项已读取但结果未包含；请单独调用。'}
            used+=size;results.append({'index':index,'tool':op['tool'],'ok':ok,'result':result})
            if not ok and stop_on_error:
                return {'ok':False,'results':results,'stopped_on_error':True,'next_index':index+1 if index+1<len(operations) else None}
        return {'ok':all(r['ok'] for r in results),'results':results,'truncated':False,'next_index':None}
