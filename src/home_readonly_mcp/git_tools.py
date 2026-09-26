"""Fixed Git actions; no caller-supplied flags, hooks, filters or implicit transport."""
from __future__ import annotations
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import shutil
import stat
from urllib.parse import urlparse
from .errors import Fault, redact
from .onboarding import child_environment
from .processes import bounded_run
from .storage import Lease, private_dir, read_bytes
from .git_branches import BranchActions

GIT_READS={'git_status','git_log','git_diff','git_branches'}
GIT_WRITES={'git_init','git_add','git_commit','git_push','git_create_branch','git_switch_branch'}


class GitTools(BranchActions):
    def __init__(self, service):
        self.service=service
        self.policy=service.policy
        self.binary=None

    def env(self, network=False):
        env=child_environment()
        # Explicit Git flags/settings, not inherited GIT_*, shell startup files or askpass.
        env.update({'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull,
            'GIT_CONFIG_SYSTEM':os.devnull,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never',
            'GIT_OPTIONAL_LOCKS':'0','GIT_NO_REPLACE_OBJECTS':'1','GIT_NO_LAZY_FETCH':'1',
            'GIT_LITERAL_PATHSPECS':'1','GIT_ALLOW_PROTOCOL':'https:ssh' if network else '',
            'GIT_PAGER':'','GIT_ATTR_NOSYSTEM':'1','LC_ALL':'C','LANG':'C'})
        if network and os.name!='nt' and os.environ.get('SSH_AUTH_SOCK'):
            env['SSH_AUTH_SOCK']=os.environ['SSH_AUTH_SOCK']
        return env

    def run(self, repo, args, *, allow_failure=False, network=False, cap=2*1024*1024):
        binary=self.binary or shutil.which('git')
        if not binary:
            raise Fault('GIT_NOT_FOUND','没有找到 Git。','PATH 中没有 git。','在本机安装 Git 后重试。')
        control=private_dir(self.policy.state_dir/'git-control')
        hooks=private_dir(control/'empty-hooks')
        template=private_dir(control/'empty-template')
        flags=['--no-pager','--no-replace-objects',
            '-c',f'core.hooksPath={hooks}','-c','core.fsmonitor=false',
            '-c',f'core.attributesFile={os.devnull}','-c',f'core.excludesFile={os.devnull}',
            '-c','commit.gpgSign=false','-c','tag.gpgSign=false','-c','maintenance.auto=false',
            '-c','gc.auto=0','-c','submodule.recurse=false','-c','diff.submodule=short',
            '-c','diff.renames=false','-c',f'init.templateDir={template}',
            '-c','credential.helper=','-c','protocol.allow=never',
            '-c','http.followRedirects=false','-c','push.recurseSubmodules=no',
            '-c','push.negotiate=false']
        if network:
            flags+=['-c','protocol.https.allow=always','-c','protocol.ssh.allow=always']
            # Only a user-configured native helper, never repository-controlled helper commands.
            if self.policy.git_credential_helper:
                flags+=['-c',f'credential.helper={self.policy.git_credential_helper}']
            ssh=shutil.which('ssh')
            if ssh:
                import shlex
                sshcmd=(f'"{ssh}" -F "{os.devnull}" -oBatchMode=yes' if os.name=='nt' else
                        f'{shlex.quote(ssh)} -F {shlex.quote(os.devnull)} -oBatchMode=yes')
                flags+=['-c',f'core.sshCommand={sshcmd}']
        env=self.env(network)
        env['GIT_CEILING_DIRECTORIES']=str(Path(repo).resolve())
        if (Path(repo)/'.git').is_dir():
            flags += ['--git-dir='+str(Path(repo)/'.git'),'--work-tree='+str(repo)]
        code,body=bounded_run([binary,*flags,*args],repo,env,
                             timeout=120 if network else 30,cap=cap)
        if code and not allow_failure:
            text=redact(body.decode('utf-8','replace'))[-12000:]
            if 'index.lock' in text or 'another git process' in text.lower():
                raise Fault('GIT_LOCKED','Git 索引/引用锁被占用。',text,
                            '确认持锁 Git 进程是否仍在运行；不自动删除 index.lock。',retryable=True,holder='unknown')
            raise Fault('GIT_COMMAND_FAILED','Git 操作失败。',text,
                        '查看退出码和原因；推送失败时检查已批准的远端及本机认证。',exit_code=code)
        return code,body

    def root(self, repo_path='.', *, initializing=False):
        p=self.policy.require(repo_path)
        if not p.is_dir():raise ValueError('repo_path must be a directory')
        if initializing:
            return p
        current=p
        while not (current/'.git').exists() and not (current/'.git').is_symlink():
            if current==self.policy.root:
                raise Fault('NOT_A_GIT_REPOSITORY','授权目录内未找到 Git 仓库。',repo_path,
                            '选择仓库或使用 git_init；不会向 root 外搜索。')
            current=current.parent
            self.policy.require(str(current))
        return current

    def metadata(self, repo):
        gitdir=repo/'.git'
        if not gitdir.is_dir() or gitdir.is_symlink() or getattr(gitdir,'is_junction',lambda:False)():
            raise Fault('UNSUPPORTED_GIT_LAYOUT','需要仓库内真实 .git 目录。',
                        'gitdir 重定向、链接 worktree 或重解析点不在当前安全模式支持范围。',
                        '使用独立工作副本；不会跟随外部 Git 元数据。')
        count=0
        for root,dirs,files in os.walk(gitdir,followlinks=False):
            for name in dirs+files:
                p=Path(root)/name;count+=1
                if count>50000:
                    raise Fault('GIT_METADATA_LIMIT','Git 元数据检查超过预算。','>50000 entries',
                                '在本机整理仓库或使用较小工作副本。')
                st=p.lstat()
                if (p.is_symlink() or getattr(p,'is_junction',lambda:False)() or
                    not p.resolve().is_relative_to(gitdir.resolve()) or
                    (stat.S_ISREG(st.st_mode) and st.st_nlink>1) or
                    not (stat.S_ISREG(st.st_mode) or stat.S_ISDIR(st.st_mode))):
                    raise Fault('UNSAFE_GIT_METADATA','Git 元数据包含链接或范围跳转。',name,
                                '使用不含外部元数据/硬链接的独立仓库。')
        for rel in ('commondir','objects/info/alternates','objects/info/http-alternates'):
            p=gitdir/rel
            if p.exists() and p.stat().st_size:
                raise Fault('UNSAFE_GIT_METADATA','Git 使用替代对象库或外部 common dir。',rel,
                            '安全模式拒绝读取外部仓库对象。')
        config=gitdir/'config'
        values=self._read_config_file(config,repo)
        enabled=self._config_bool(config,'extensions.worktreeconfig')
        worktree_config=gitdir/'config.worktree'
        # Validate the separate file BEFORE any Git command reads repository settings.
        # Also inspect dormant files; a later config change must not activate unchecked hooks/includes.
        if worktree_config.exists():
            extra=self._read_config_file(worktree_config,repo,worktree=True)
            if enabled:
                for key,items in extra.items():
                    values.setdefault(key,[]).extend(items)
        return values

    def _config_bool(self,path,key):
        control=private_dir(self.policy.state_dir/'git-control')
        code,data=self.run(control,['config','--file',str(path),'--no-includes',
                                    '--type=bool','--get',key],allow_failure=True)
        if code==1:return False
        if code or data.strip() not in (b'true',b'false'):
            raise Fault('INVALID_GIT_CONFIG','Git 配置布尔值无效。',key,
                        '在本机检查配置；不显示配置值或自动修改。')
        return data.strip()==b'true'

    def _read_config_file(self,path,repo,worktree=False):
        try:st=path.lstat()
        except FileNotFoundError:
            raise Fault('INVALID_GIT_CONFIG','Git 配置缺失。','config','在本机检查仓库。') from None
        if not stat.S_ISREG(st.st_mode) or st.st_nlink!=1 or st.st_size>262144:
            raise Fault('INVALID_GIT_CONFIG','Git 配置不是有界的普通文件。',path.name,
                        '在本机检查配置；不跟随符号链接、硬链接或特殊文件。')
        control=private_dir(self.policy.state_dir/'git-control')
        code,data=self.run(control,['config','--file',str(path),'--no-includes','--null','--list'],
                           allow_failure=True)
        if code:
            raise Fault('INVALID_GIT_CONFIG','Git 配置解析失败。',path.name,
                        '在本机检查配置语法；不返回可能含敏感信息的解析错误。')
        values={}
        for entry in data.split(b'\0'):
            if not entry:continue
            key,_,value=entry.decode('utf-8','strict').partition('\n')
            k=key.lower();values.setdefault(k,[]).append(value)
            unsafe=(k.startswith(('include.','includeif.','filter.','url.','credential.','http.')) or
                    k in ('core.sshcommand','core.gitproxy','commit.template','extensions.partialclone') or
                    (k.startswith('remote.') and k.endswith(('.uploadpack','.receivepack','.promisor','.vcs'))))
            if k=='core.worktree':
                candidate=Path(value)
                if not candidate.is_absolute():candidate=repo/'.git'/candidate
                # A same-target symlink alias is still a mutable redirection, not the
                # canonical worktree. Permit '..' and canonical absolute paths only
                # when lexical and resolved locations agree and no component is linked.
                linked=any(p.is_symlink() or getattr(p,'is_junction',lambda:False)()
                           for p in (candidate,*candidate.parents))
                unsafe=(not worktree or linked or
                        Path(os.path.abspath(candidate))!=repo.resolve() or
                        candidate.resolve()!=repo.resolve())
            if worktree and k.startswith('extensions.'):
                unsafe=True  # Extensions belong to the common configuration, not the overlay.
            if unsafe:
                raise Fault('UNSAFE_GIT_CONFIG','仓库配置含安全模式禁止的扩展/外部调用。',key,
                            '在本机审核该配置；不会执行 hook/filter/helper 或展开外部 include。',
                            config_file=path.name)
        if self._config_bool(path,'core.bare'):
            raise Fault('UNSUPPORTED_GIT_LAYOUT','不支持裸仓库工作区操作。',path.name,
                        '使用非裸的独立工作副本；不会更改 core.bare。')
        return values

    @contextmanager
    def operation(self, repo_path='.', *, write=False, initializing=False):
        repo=self.root(repo_path,initializing=initializing)
        if write:
            self.policy.resolve(str(repo/'.local-mcp-git-scope'),write=True)
            self.service.commands.guard_mutation([repo])
        with Lease(self.policy.state_dir,repo/'.git','git_operation'):
            config={} if initializing and not (repo/'.git').exists() else self.metadata(repo)
            yield repo,config

    def safe_paths(self,repo,raw,write=False,strict=False):
        selected=[];denied=0
        for name in dict.fromkeys(raw):
            try:
                p=self.policy.require(str(repo/name),write=write,must_exist=False)
                if p.is_symlink() or (repo/name).is_symlink():raise ValueError('symbolic link')
                if p.is_file():
                    st=p.stat()
                    if st.st_nlink>1 or st.st_size>self.policy.max_file_size:
                        raise ValueError('hard-linked or oversized file')
                # Do not stage nested repositories or Git's file-like symlink blobs.
                if any((a/'.git').exists() for a in p.parents if a!=repo and a.is_relative_to(repo)):
                    raise ValueError('nested repository')
                selected.append(name)
            except (Fault,OSError,ValueError):
                denied+=1
                if strict:
                    raise Fault('GIT_PATH_DENIED','Git 操作包含不允许的文件。','路径、大小、链接或凭据规则拒绝。',
                                '检查暂存区及授权范围；未执行本次修改。') from None
        return selected,denied

    def names(self,repo,args):
        _,data=self.run(repo,[*args,'-z'])
        return [x.decode('utf-8','strict') for x in data.split(b'\0') if x]

    def status(self,repo_path='.'):
        with self.operation(repo_path) as (repo,_):
            _,data=self.run(repo,['status','--porcelain=v1','-z','--untracked-files=all','--ignore-submodules=all'])
            parts=data.split(b'\0');rows=[];blocked=0;i=0
            while i<len(parts) and parts[i]:
                record=parts[i].decode('utf-8','strict');i+=1
                status,name=record[:2],record[3:]
                source=None
                if 'R' in status or 'C' in status:
                    source=parts[i].decode('utf-8','strict');i+=1
                names=[name]+([source] if source else [])
                _,count=self.safe_paths(repo,names)
                if count:blocked+=1;continue
                rows.append({'path':name,'status':status,'source':source})
            return {'ok':True,'repo':self.policy.relative(repo),'entries':rows[:500],
                    **self._head_info(repo),'truncated':len(rows)>500,'blocked_entries':blocked}

    def log(self,repo_path='.',count=10):
        if not 1<=count<=50:raise ValueError('count 1..50')
        with self.operation(repo_path) as (repo,_):
            code,data=self.run(repo,['rev-parse','--verify','HEAD'],allow_failure=True)
            if code:return {'ok':True,'commits':[],'unborn_head':True}
            _,body=self.run(repo,['log',f'-{count}','--no-show-signature','--no-notes',
                                 '--format=%H%x00%an%x00%aI%x00%s%x00'])
            parts=body.decode('utf-8','replace').split('\0');out=[]
            for i in range(0,len(parts)-3,4):
                out.append({'sha':parts[i].strip(),'author':redact(parts[i+1]),
                            'date':parts[i+2],'subject':redact(parts[i+3])})
            return {'ok':True,'commits':out}

    def diff(self,repo_path='.',paths=None,staged=False):
        with self.operation(repo_path) as (repo,_):
            args=['diff','--no-ext-diff','--no-textconv','--no-renames','--ignore-submodules=all']
            if staged:args.append('--cached')
            names=self.names(repo,[*args,'--name-only'])
            names,blocked=self.safe_paths(repo,names)
            if paths is not None:
                if not isinstance(paths,list) or len(paths)>128:raise ValueError('paths must be <=128 literal paths')
                wanted=[]
                for path in paths:
                    p=self.policy.require(str(repo/path),must_exist=False)
                    wanted.append(p.relative_to(repo).as_posix())
                names=[n for n in names if any(n==w or n.startswith(w.rstrip('/')+'/') or w=='.' for w in wanted)]
            pieces=[];size=0;truncated=False
            for name in names:
                _,data=self.run(repo,[*args,'--',name],cap=2*1024*1024)
                room=self.policy.max_text_output_bytes-size
                pieces.append(data[:room].decode('utf-8','replace'));size+=min(room,len(data))
                if len(data)>room:truncated=True;break
            return {'ok':True,'diff':redact(''.join(pieces)),'staged':staged,
                    'blocked_files':blocked,'truncated':truncated}

    def init(self,repo_path='.'):
        with self.operation(repo_path,write=True,initializing=True) as (repo,_):
            if (repo/'.git').exists():return {'ok':True,'created':False,'repo':self.policy.relative(repo)}
            self.run(repo,['init','--initial-branch=main','.'])
            return {'ok':True,'created':True,'repo':self.policy.relative(repo)}

    def add(self,repo_path='.',paths=None):
        paths=['.'] if paths is None else paths
        if not isinstance(paths,list) or not 1<=len(paths)<=128:raise ValueError('paths must contain 1..128 literal paths')
        with self.operation(repo_path,write=True) as (repo,_):
            for name in paths:
                self.policy.require(str(repo/name),must_exist=False)
            _,body=self.run(repo,['ls-files','--cached','--others','--exclude-standard','-z','--',*paths])
            names=[x.decode('utf-8','strict') for x in body.split(b'\0') if x]
            names,blocked=self.safe_paths(repo,names,write=True,strict=True)
            if not names:return {'ok':True,'staged_paths':[]}
            if sum(len(x.encode())+1 for x in names)>24000:
                raise Fault('GIT_PATH_BUDGET','待暂存路径过多。','避免超过平台 argv 上限。','分批 git_add。')
            # Filters are rejected by metadata(), so git add cannot invoke repo-supplied programs.
            self.run(repo,['add','--all','--',*names])
            return {'ok':True,'staged_paths':names,'blocked_paths':blocked}

    def commit(self,repo_path='.',message='update'):
        if not message or len(message)>16000:raise ValueError('message must be 1..16000 characters')
        with self.operation(repo_path,write=True) as (repo,config):
            names=self.names(repo,['diff','--cached','--name-only','--no-renames','--no-ext-diff','--no-textconv'])
            self.safe_paths(repo,names,write=True,strict=True)
            if not names:raise Fault('GIT_NOTHING_STAGED','没有暂存修改。','未创建空提交。','先 git_add。')
            name=self.policy.git_user_name or config.get('user.name',[''])[-1]
            email=self.policy.git_user_email or config.get('user.email',[''])[-1]
            if not name or not email:
                raise Fault('GIT_IDENTITY_MISSING','尚未设置提交身份。','没有本机配置或仓库级 user.name/user.email。',
                            '在本机配置 git_user_name/git_user_email，或设置仓库 Git 身份。')
            self.run(repo,['-c',f'user.name={name}','-c',f'user.email={email}',
                          'commit','--no-gpg-sign','--no-verify','-m',message])
            _,sha=self.run(repo,['rev-parse','HEAD'])
            return {'ok':True,'commit_sha':sha.decode().strip(),'files':names}

    def push(self,repo_path='.',remote='origin'):
        if not self.policy.enable_git_push:
            raise Fault('GIT_PUSH_DISABLED','Git 推送未启用。','enable_git_push=false。','在本机明确开启并配置远端 URL 白名单。')
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}',remote):raise ValueError('invalid remote name')
        with self.operation(repo_path,write=True) as (repo,config):
            urls=config.get(f'remote.{remote}.pushurl') or config.get(f'remote.{remote}.url',[])
            if len(urls)!=1:raise Fault('GIT_REMOTE_INVALID','远端必须只有一个明确 URL。',remote,'在本机检查 remote 配置。')
            url=urls[0];parsed=urlparse(url)
            scp=bool(re.fullmatch(r'[A-Za-z0-9_.-]+@[A-Za-z0-9.-]+:[A-Za-z0-9_./-]+',url))
            if not (scp or parsed.scheme in ('https','ssh')) or parsed.password or parsed.query or parsed.fragment:
                raise Fault('GIT_TRANSPORT_DENIED','远端传输类型或 URL 不允许。','仅支持无内嵌密码的 HTTPS/SSH。',
                            '不支持本地文件、ext helper 或携带密钥的 URL。')
            if url not in self.policy.git_push_remotes:
                raise Fault('GIT_REMOTE_NOT_APPROVED','远端未列入本机推送白名单。',remote,
                            '用户在本机审核 URL 后加入 git_push_remotes；模型不能修改白名单。')
            _,branch=self.run(repo,['symbolic-ref','--quiet','--short','HEAD'])
            branch=branch.decode().strip()
            self.run(repo,['check-ref-format','--branch',branch])
            # Only current branch -> same-named remote branch; no force, tags, mirror or delete.
            _,output=self.run(repo,['push','--porcelain','--no-verify','--recurse-submodules=no',
                                   url,f'HEAD:refs/heads/{branch}'],network=True)
            return {'ok':True,'remote':remote,'branch':branch,'output':redact(output.decode('utf-8','replace'))}


class GitMixin:
    def git_branches(self,repo_path='.',offset=0,limit=100):
        return self.git.branches(repo_path,offset,limit)
    def git_create_branch(self,branch,repo_path='.',checkout=True,expected_head=None):
        return self.git.create_branch(branch,repo_path,checkout,expected_head)
    def git_switch_branch(self,branch,repo_path='.',expected_head=None):
        return self.git.switch_branch(branch,repo_path,expected_head)
    def git_init(self,repo_path='.'):
        return self.git.init(repo_path)
    def git_status(self,repo_path='.'):
        return self.git.status(repo_path)
    def git_log(self,repo_path='.',count=10):
        return self.git.log(repo_path,count)
    def git_diff(self,repo_path='.',paths=None,staged=False):
        return self.git.diff(repo_path,paths,staged)
    def git_add(self,repo_path='.',paths=None):
        return self.git.add(repo_path,paths)
    def git_commit(self,repo_path='.',message='update'):
        return self.git.commit(repo_path,message)
    def git_push(self,repo_path='.',remote='origin'):
        return self.git.push(repo_path,remote)
