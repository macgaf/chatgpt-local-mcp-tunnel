"""Local-only browser/keystore preparation, not an MCP filesystem tool.

This module closes the missing browser -> native keystore handoff. The agent
may navigate public form controls, but the submit/capture/store sequence runs
inside one process. Only fixed status fields leave that process. Site adapters
are deliberately conservative: unobservable selections block submission.
"""
from __future__ import annotations
from dataclasses import dataclass
import json
import hashlib
from pathlib import Path
import re
import secrets
import time
import urllib.error
import urllib.request

from .browser_local import LocalBrowser, BrowserFailure, configured_browser_argv
from .credentials import native_backend, validate_key, load_key
from .onboarding import load_settings, save_settings
from .policy import APP, locations
from .storage import Lease, private_dir, write_private

ORIGIN = 'https://platform.openai.com'
TUNNELS = '/settings/organization/tunnels'
KEYS = '/settings/organization/api-keys'
ID_PATTERN = re.compile(r'tunnel_[0-9a-f]{32}')


class PreparationFailure(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


ACTIONS = {
    'CHROME_DEBUG_ENDPOINT_MISSING': '在本机 Chrome 的 chrome://inspect/#remote-debugging 确认允许调试，再重跑预检；不需要 Apple Events。',
    'CHROME_CONNECTION_OR_APPROVAL_REQUIRED': '确认 Chrome 运行，并在 Chrome 本人批准调试连接；不猜端口或改用 AppleScript。',
    'BROWSER_APPROVAL_REQUIRED': '由本人批准 Chrome 调试连接；不绕过浏览器授权。',
    'BROWSER_TIMEOUT': '检查 Chrome 是否等待本人确认或连接失效；未提交任何后续创建。',
    'KEYSTORE_UNAVAILABLE': '在本机开发/安装虚拟环境安装 keyring，并确认系统凭据库可用。',
    'KEYSTORE_PROBE_FAILED': '检查系统凭据库解锁或授权；不要先创建真实 key。',
    'TRANSFER_PROBE_FAILED': '浏览器到凭据库的虚构值端到端探针失败；禁止创建真实 key。',
    'PERMISSION_SELECTION_NOT_APPLIED': 'Read/Use 的真实选中状态未通过。重新打开 Tunnels 权限菜单核对；不以点击次数判断成功。',
    'PERMISSION_PROOF_INCOMPLETE': '必须证明 Restricted、仅 Read+Use、其他资源均无权限；当前页面不足以验证，未创建 key。',
    'FORM_LAYOUT_UNSUPPORTED': '站点控件布局未被当前适配器识别。只查看标签/角色/布尔状态，不能放宽验证或返回原始 DOM。',
    'TARGET_CONFIRMATION_REQUIRED': '按组织和 ChatGPT 工作区名称确认目标一次；Platform 项目不是 ChatGPT 工作区。',
    'TUNNEL_NOT_FOUND': '未找到本项目专用 Tunnel；先在网页准备创建表单，确认目标后使用 submit-tunnel。不要抢占 FileMCP 的 Tunnel。',
    'TUNNEL_AMBIGUOUS': '同名 Tunnel 不唯一，需要本人在网站确认，不自动选择或重建。',
    'TUNNEL_ASSOCIATION_MISSING': '该 Tunnel 未观察到组织或 ChatGPT 工作区关联；先修复关联，不重复创建 key。',
    'BINDING_CONFLICT': '已有本机 Tunnel 绑定不同，未覆盖；核对目标后由本人决定。',
    'KEY_ALREADY_CACHED': '本机已存在此 Tunnel 的 key，不覆盖或重复创建；先核查权限和认证。',
    'CREATION_OUTCOME_UNCERTAIN': '上次创建状态不明确；检查现有列表或一次性显示弹窗，不再次点击创建。',
    'KEY_NOT_CAPTURED': '未取得唯一完整新 key；保留弹窗，停止重复创建，不将掩码当作完整值。',
    'KEYSTORE_SAVE_FAILED': '保存或读回失败；保留一次性密钥弹窗和原配置，不关闭或再次创建。',
    'KEY_SOURCE_UNSUPPORTED': '保留原有 systemd/environment 凭据来源；本网页保存助手只写 native keyring，不擅自迁移。',
    'CONFIG_CHANGED': '执行期间本机配置变化，未覆盖新配置；保留已生成资源，核对后恢复。',
    'UNTRUSTED_PAGE': '当前页面不是预期的 OpenAI 设置页面；先完成登录或回到正确页面。',
    'CREATE_NOT_AUTHORIZED': '实际提交创建需要显式 --allow-create；检查/缓存阶段不会创建云端资源。',
}


def failure_payload(exc, stage):
    # No exception text/args, browser response, URL, selectors or native error
    # details can be serialized here; even unexpected exceptions are status-only.
    code = getattr(exc, 'code', 'PREPARATION_FAILED')
    if not isinstance(code, str) or not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}', code):
        code = 'PREPARATION_FAILED'
    return {'ok':False, 'stage':stage, 'error_code':code,
        'remediation':ACTIONS.get(code, '检查本机浏览器连接、依赖和已选目标；不输出原始浏览器结果，不盲目重试创建。'),
        'exception_type':type(exc).__name__, 'credentials_returned':False}


def credential_probe(backend, value=None):
    account = 'setup-probe-' + secrets.token_hex(16)
    service = APP + '/setup-probe'
    value = value or 'not-a-real-key-' + secrets.token_hex(32)
    created = False
    try:
        backend.set_password(service, account, value)
        created = True
        if backend.get_password(service, account) != value:
            raise PreparationFailure('KEYSTORE_PROBE_FAILED')
    finally:
        if created:
            backend.delete_password(service, account)


@dataclass
class Node:
    uid: str
    indent: int
    role: str
    name: str
    flags: str

    @property
    def checked(self):
        if re.search(r'\b(?:checked|pressed|selected)(?:=|:)(?:false|"false")', self.flags):
            return False
        return bool(re.search(r'\b(?:checked|pressed|selected)(?:\s|$|=true|="true")', self.flags))


def nodes(snapshot):
    out = []
    for line in snapshot.splitlines():
        match = re.match(r'^(\s*)uid=(\S+)\s+(\w+)\s+"((?:\\.|[^"\\])*)"(.*)$', line)
        if not match:
            continue
        indent, uid, role, name, flags = match.groups()
        try:
            name = json.loads('"'+name+'"')
        except ValueError:
            continue
        out.append(Node(uid,len(indent),role,name,flags))
    return out


def only_node(items, roles, names):
    found = [n for n in items if n.role in roles and n.name in names and 'disabled' not in n.flags]
    if len(found) != 1:
        raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
    return found[0]


def assert_permission_proof(proof):
    # A successful click, visible label, or number of attempted clicks is not
    # evidence that a React-controlled menu item stayed selected.
    required = ('restricted','read_checked','use_checked','others_none','project_selected')
    if not isinstance(proof,dict) or any(proof.get(k) is not True for k in required) or proof.get('selected_count') != 2:
        raise PreparationFailure('PERMISSION_PROOF_INCOMPLETE')


class PlatformPage:
    def __init__(self, browser):
        self.browser = browser

    def open(self, path):
        if path not in (TUNNELS,KEYS):
            raise PreparationFailure('UNTRUSTED_PAGE')
        raw = self.browser.text(self.browser.call('list_pages'))
        matches = []
        for line in raw.splitlines():
            found = re.match(r'\s*(\d+):.*?\((https://platform\.openai\.com[^)]*)\)',line)
            if found and found.group(2).split('?')[0].rstrip('/') == ORIGIN+path:
                matches.append(int(found.group(1)))
        if len(matches)>1:
            raise PreparationFailure('PLATFORM_TAB_AMBIGUOUS')
        if matches:
            self.browser.call('select_page',{'pageId':matches[0],'bringToFront':False})
        else:
            self.browser.call('new_page',{'url':ORIGIN+path,'background':True,'timeout':20000})
        self.guard(path)

    def guard(self,path):
        result = self.browser.evaluate('() => ({origin:location.origin,path:location.pathname})')
        if result.get('origin')!=ORIGIN or result.get('path','').rstrip('/')!=path:
            raise PreparationFailure('UNTRUSTED_PAGE')

    def click(self,node):
        self.browser.call('click',{'uid':node.uid})
        time.sleep(.15)

    def key_nodes(self):
        self.guard(KEYS)
        all_nodes = nodes(self.browser.snapshot())
        # Restrict label lookup to the key-creation dialog, not background tables.
        starts = [i for i,n in enumerate(all_nodes) if n.role=='dialog' and 'secret key' in n.name.casefold()]
        if len(starts)!=1:
            raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        start = starts[0]; depth=all_nodes[start].indent
        end = next((i for i in range(start+1,len(all_nodes)) if all_nodes[i].indent<=depth),len(all_nodes))
        return all_nodes[start:end]

    def permission_menu(self):
        self.guard(KEYS)
        current=nodes(self.browser.snapshot())
        options=[n for n in current if n.role in ('menuitemcheckbox','checkbox','option') and n.name in ('Read','Use')]
        if len(options)==2:
            return current
        dialog=self.key_nodes()
        rows=[i for i,n in enumerate(dialog) if n.role=='row' and re.match(r'^Tunnels(?:\s|$)',n.name)]
        if len(rows)!=1:
            raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        start=rows[0];depth=dialog[start].indent
        end=next((i for i in range(start+1,len(dialog)) if dialog[i].indent<=depth),len(dialog))
        buttons=[n for n in dialog[start+1:end] if n.role in ('button','combobox') and 'disabled' not in n.flags]
        if len(buttons)!=1:
            raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        self.click(buttons[0])
        return nodes(self.browser.snapshot())

    def permission_proof(self):
        menu=self.permission_menu()
        read=only_node(menu,('menuitemcheckbox','checkbox','option'),('Read',))
        use=only_node(menu,('menuitemcheckbox','checkbox','option'),('Use',))
        restricted=[n for n in menu if n.name=='Restricted' and n.role in ('radio','button','tab')]
        details=self.browser.evaluate(r'''() => {
          const d=[...document.querySelectorAll('[role="dialog"]')].find(e=>/Create new secret key/i.test(e.innerText||''));
          if(!d)return {observable:false};
          const rows=[...d.querySelectorAll('tr')].map(e=>[...e.querySelectorAll('td')].map(c=>(c.innerText||'').trim()));
          const permissions=rows.filter(c=>c.length===2 && c[0] && c[1]);
          const other=permissions.filter(c=>c[0]!=='Tunnels');
          const count=(d.innerText||'').match(/(\d+)\s+selected permissions/i);
          const project=[...d.querySelectorAll('button,[role="combobox"],[role="button"]')].some(e=>/Default project|project/i.test((e.innerText||''))&&!/select.*project|choose.*project/i.test(e.innerText||''));
          return {observable:permissions.some(c=>c[0]==='Tunnels'),others_none:other.length>0&&other.every(c=>c[1]==='None'),selected_count:count?Number(count[1]):null,project_selected:project};
        }''')
        return {'restricted':len(restricted)==1 and restricted[0].checked,
            'read_checked':read.checked,'use_checked':use.checked,
            'others_none':details.get('observable') is True and details.get('others_none') is True,
            'selected_count':details.get('selected_count'), 'project_selected':details.get('project_selected') is True}

    def select_permissions(self):
        self.guard(KEYS)
        dialog=self.key_nodes()
        restricted=only_node(dialog,('radio','button','tab'),('Restricted',))
        if not restricted.checked:
            self.click(restricted)
        for name in ('Read','Use'):
            # Reopen after each change: menu closure or a stale node cannot be
            # interpreted as a retained selection.
            item=only_node(self.permission_menu(),('menuitemcheckbox','checkbox','option'),(name,))
            if not item.checked:
                self.click(item)
            post=only_node(self.permission_menu(),('menuitemcheckbox','checkbox','option'),(name,))
            if not post.checked:
                raise PreparationFailure('PERMISSION_SELECTION_NOT_APPLIED')
        proof=self.permission_proof()
        assert_permission_proof(proof)
        self.browser.call('press_key',{'key':'Escape'})
        return proof

    def tunnel_record(self,name):
        self.open(TUNNELS)
        # Contents never leave this local process. No full DOM/outerHTML,
        # screenshots, network response bodies or browser storage is fetched.
        records=self.browser.evaluate(r'''() => [...document.querySelectorAll('table')].flatMap(t=>{
          const headers=[...t.querySelectorAll('thead th')].map(x=>(x.innerText||'').trim().toUpperCase());
          const index=k=>headers.indexOf(k);
          if(index('ID')<0||index('WORKSPACES')<0||index('ORGANIZATIONS')<0)return [];
          return [...t.querySelectorAll('tbody tr')].slice(0,200).map(r=>{
            const c=[...r.querySelectorAll('td')].map(x=>(x.innerText||'').trim());
            return {name:c[index('TUNNEL')>=0?index('TUNNEL'):index('NAME')],id:c[index('ID')],organizations:c[index('ORGANIZATIONS')],workspaces:c[index('WORKSPACES')]};
          });
        })''')
        matches=[x for x in records if x.get('name')==name]
        if not matches:raise PreparationFailure('TUNNEL_NOT_FOUND')
        if len(matches)!=1:raise PreparationFailure('TUNNEL_AMBIGUOUS')
        record=matches[0]
        ids=ID_PATTERN.findall(record.get('id',''))
        if len(ids)!=1:raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        record['id']=ids[0]
        if any(record.get(k,'').strip() in ('','-','—','None') for k in ('organizations','workspaces')):
            raise PreparationFailure('TUNNEL_ASSOCIATION_MISSING')
        return record

    def tunnel_form(self, name):
        self.guard(TUNNELS)
        result=self.browser.evaluate(r'''() => {
          const ds=[...document.querySelectorAll('[role="dialog"]')].filter(e=>/create.*tunnel/i.test(e.innerText||''));
          if(ds.length!==1)return {observable:false};
          const fields=[...ds[0].querySelectorAll('input,textarea,select')].map(e=>({
            label:((e.labels&&[...e.labels].map(x=>x.innerText).join(' '))||e.getAttribute('aria-label')||e.name||'').toLowerCase(),
            value:String(e.value||'').trim()
          }));
          const matching=word=>fields.filter(f=>f.label.includes(word)&&f.value).map(f=>f.value);
          return {observable:true,names:matching('name'),organizations:matching('organization'),workspaces:matching('workspace')};
        }''')
        if result.get('observable') is not True or result.get('names')!=[name] or not result.get('organizations') or not result.get('workspaces'):
            raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        return result

    def submit_tunnel(self, name):
        self.tunnel_form(name)
        all_nodes=nodes(self.browser.snapshot())
        dialogs=[i for i,n in enumerate(all_nodes) if n.role=='dialog' and re.search(r'create.*tunnel',n.name,re.I)]
        if len(dialogs)!=1:raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        start=dialogs[0];depth=all_nodes[start].indent
        end=next((i for i in range(start+1,len(all_nodes)) if all_nodes[i].indent<=depth),len(all_nodes))
        submit=only_node(all_nodes[start:end],('button',),('Create','Create tunnel','Create Tunnel'))
        self.click(submit)

    def secret(self, ownership):
        self.guard(KEYS)
        if not re.fullmatch(r'[0-9a-f]{32}',ownership or ''):raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
        result=self.browser.evaluate(r'''() => {
          const marker=window.__localMcpKeyPreparation;
          if(!marker||marker.nonce!==NONCE||!marker.resultDialog?.isConnected)return {values:[]};
          const candidates=[...marker.resultDialog.querySelectorAll('input,textarea,code')].map(e=>e.value||e.textContent||'');
          const values=[...new Set(candidates.flatMap(v=>v.match(/sk-[A-Za-z0-9_-]{16,4096}/g)||[]))];
          return {values};
        }'''.replace('NONCE',json.dumps(ownership)))
        values=result.get('values',[])
        if len(values)!=1:raise PreparationFailure('KEY_NOT_CAPTURED')
        return validate_key(values[0])

    def submit_key(self,key_name,ownership):
        self.guard(KEYS)
        proof=self.permission_proof()
        assert_permission_proof(proof)
        self.browser.call('press_key',{'key':'Escape'})
        dialog=self.key_nodes()
        names=[n for n in dialog if n.role=='textbox' and re.match(r'^Name(?:\s|$)',n.name)]
        if len(names)!=1:raise PreparationFailure('FORM_LAYOUT_UNSUPPORTED')
        self.browser.call('fill',{'uid':names[0].uid,'value':key_name})
        # Revalidate immediately before final submission; not just at an earlier click.
        proof=self.permission_proof();assert_permission_proof(proof)
        self.browser.call('press_key',{'key':'Escape'})
        submit=only_node(self.key_nodes(),('button',),('Create secret key','Create key'))
        if not re.fullmatch(r'[0-9a-f]{32}',ownership):raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
        # Observe only this pending creation's first result dialog, then stop.
        # A retry cannot harvest a later, unrelated manually-created key popup.
        ready=self.browser.evaluate(r'''() => {
          if(window.__localMcpKeyPreparation?.observer)window.__localMcpKeyPreparation.observer.disconnect();
          const ds=[...document.querySelectorAll('[role="dialog"]')];
          const source=ds.find(d=>/Create new secret key/i.test(d.innerText||''));
          if(!source||ds.some(d=>[...d.querySelectorAll('input,textarea,code')].some(e=>/^sk-[A-Za-z0-9_-]{16,}/.test(e.value||e.textContent||''))))return {ready:false};
          const marker={nonce:NONCE,resultDialog:null,observer:null};
          const observer=new MutationObserver(()=>{
            const candidates=[...document.querySelectorAll('[role="dialog"]')].filter(d=>[...d.querySelectorAll('input,textarea,code')].some(e=>/^sk-[A-Za-z0-9_-]{16,}/.test(e.value||e.textContent||'')));
            if(candidates.length===1){marker.resultDialog=candidates[0];observer.disconnect();}
          });
          marker.observer=observer;window.__localMcpKeyPreparation=marker;
          observer.observe(document.body,{childList:true,subtree:true,attributes:true});
          setTimeout(()=>observer.disconnect(),30000);
          return {ready:true};
        }'''.replace('NONCE',json.dumps(ownership)))
        if ready.get('ready') is not True:raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
        self.click(submit)


class RejectRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise PreparationFailure('AUTH_REDIRECT_REJECTED')


def verify_read(settings,backend=None):
    ident=settings.get('tunnel_id','')
    if not ID_PATTERN.fullmatch(ident):raise PreparationFailure('TUNNEL_NOT_FOUND')
    value=load_key(settings,backend=backend)
    request=urllib.request.Request('https://api.openai.com/v1/tunnels/'+ident,
        headers={'Authorization':'Bearer '+value,'Accept':'application/json'})
    try:
        with urllib.request.build_opener(RejectRedirects()).open(request,timeout=15) as response:
            body=response.read(256*1024+1)
            if len(body)>256*1024:raise PreparationFailure('AUTH_RESPONSE_TOO_LARGE')
            data=json.loads(body)
            if data.get('id')!=ident and data.get('tunnel_id')!=ident:
                raise PreparationFailure('AUTH_TARGET_NOT_VERIFIED')
        return {'read_authentication':'passed','use_authentication':'not_checked',
            'note':'读取认证通过不等于 Use 权限和 ChatGPT 连接通过；安装后继续官方 Tunnel 诊断。'}
    except urllib.error.HTTPError as exc:
        return {'read_authentication':'failed','http_status':exc.code,'use_authentication':'not_checked'}
    except (urllib.error.URLError, TimeoutError):
        return {'read_authentication':'network_failed','use_authentication':'not_checked'}


class Preparation:
    def __init__(self,config_path,backend=None,browser_factory=None):
        self.config=Path(config_path).expanduser()
        self.backend=backend
        self.browser_factory=browser_factory or (lambda:LocalBrowser(configured_browser_argv(),Path.cwd()))
        self.journal=self.config.parent/'browser-preparation.json'

    def store(self):
        if self.backend is None:self.backend=native_backend()
        return self.backend

    def preflight(self):
        checks=[];backend=None
        try:
            backend=self.store();credential_probe(backend)
            checks.append({'name':'native_keystore','status':'pass'})
        except Exception as exc:
            checks.append({'name':'native_keystore','status':'fail',**failure_payload(exc,'preflight')})
        try:
            with self.browser_factory() as b:
                b.call('list_pages')
                # Run only on the expected public settings origin. Existing
                # secret dialogs stay open; this script reads no page content.
                page=PlatformPage(b);page.open(TUNNELS)
                value=b.evaluate('() => "not-a-real-key-" + crypto.randomUUID()')
                if not isinstance(value,str) or not value.startswith('not-a-real-key-'):
                    raise PreparationFailure('TRANSFER_PROBE_FAILED')
                if backend is not None:
                    credential_probe(backend,value)
                    checks.append({'name':'browser_to_keystore_memory_roundtrip','status':'pass'})
                else:checks.append({'name':'browser_to_keystore_memory_roundtrip','status':'not_checked'})
                checks.append({'name':'authorized_browser','status':'pass'})
        except Exception as exc:
            checks.append({'name':'authorized_browser','status':'fail',**failure_payload(exc,'preflight')})
        return {'ok':all(x['status']=='pass' for x in checks),'stage':'preflight','checks':checks,
            'cloud_mutations':False,'uses_apple_events':False,'writes_browser_payload_to_file':False,
            'credentials_returned':False}

    def read_journal(self):
        if self.journal.is_symlink():raise PreparationFailure('UNSAFE_STATE_PATH')
        if not self.journal.exists():return {}
        st=self.journal.stat()
        if st.st_nlink!=1 or st.st_size>65536:raise PreparationFailure('UNSAFE_STATE_PATH')
        result=json.loads(self.journal.read_text(encoding='utf-8'))
        if not isinstance(result,dict):raise PreparationFailure('UNSAFE_STATE_PATH')
        return result

    def _journal(self,data):
        # Progress contains no key; only our exact target identifier and state.
        # It is not a replacement config: binding is saved through save_settings.
        private_dir(self.journal.parent)
        if self.journal.is_symlink():raise PreparationFailure('UNSAFE_STATE_PATH')
        temp=self.journal.with_name('browser-preparation-'+secrets.token_hex(8)+'.tmp')
        write_private(temp,json.dumps(data).encode())
        temp.replace(self.journal)

    def bind(self,name,confirm_target=False):
        if not confirm_target:raise PreparationFailure('TARGET_CONFIRMATION_REQUIRED')
        before=load_settings(self.config)
        with self.browser_factory() as b:
            record=PlatformPage(b).tunnel_record(name)
        if before.get('tunnel_id') not in (None,record['id']):raise PreparationFailure('BINDING_CONFLICT')
        if load_settings(self.config)!=before:raise PreparationFailure('CONFIG_CHANGED')
        after={**before,'tunnel_id':record['id']}
        after.setdefault('key_source','keyring')
        save_settings(self.config,after)
        return {'ok':True,'stage':'cache-tunnel','tunnel':'cached','association_present':True,
            'target_confirmed_by_operator':True,'permissions_changed':False,'credentials_returned':False}

    def finish_tunnel(self,name,allow_create=False,confirm_target=False):
        if not confirm_target:raise PreparationFailure('TARGET_CONFIRMATION_REQUIRED')
        before=load_settings(self.config)
        if before.get('tunnel_id'):return self.bind(name,confirm_target=True)
        self.store();credential_probe(self.backend)
        pending=self.read_journal()
        if pending.get('state','').endswith('_pending') and pending.get('state')!='tunnel_creation_pending':
            raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
        created=False
        with self.browser_factory() as b:
            page=PlatformPage(b);page.open(TUNNELS)
            try:record=page.tunnel_record(name)
            except PreparationFailure as exc:
                if exc.code!='TUNNEL_NOT_FOUND':raise
                record=None
            if record is None:
                if pending.get('state','').endswith('_pending'):raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
                if not allow_create:raise PreparationFailure('CREATE_NOT_AUTHORIZED')
                proof=page.tunnel_form(name)
                self._journal({'state':'tunnel_creation_pending','name':name,'scope':proof,'created_at':time.time()})
                page.submit_tunnel(name)
                created=True
                for attempt in range(20):
                    try:record=page.tunnel_record(name);break
                    except PreparationFailure as exc:
                        if exc.code!='TUNNEL_NOT_FOUND':raise
                        time.sleep(.25)
                if record is None:raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
                # Compare values available in both form and row. A label/ID
                # mapping mismatch is a real review step, never assumed equal.
                if any(value not in record[field] for field in ('organizations','workspaces') for value in proof[field]):
                    raise PreparationFailure('TUNNEL_TARGET_NOT_VERIFIED')
            if pending.get('state')=='tunnel_creation_pending':
                proof=pending.get('scope',{})
                if pending.get('name')!=name or any(not proof.get(field) or any(value not in record[field] for value in proof[field]) for field in ('organizations','workspaces')):
                    raise PreparationFailure('TUNNEL_TARGET_NOT_VERIFIED')
            if load_settings(self.config)!=before:raise PreparationFailure('CONFIG_CHANGED')
            after={**before,'tunnel_id':record['id']};after.setdefault('key_source','keyring')
            save_settings(self.config,after)
            self._journal({'state':'tunnel_cached','tunnel_id':record['id'],'name':name,'saved_at':time.time()})
        return {'ok':True,'stage':'submit-tunnel','tunnel':'created' if created else 'reused','association_present':True,
            'permissions_changed':False,'credentials_returned':False}

    def finish_key(self,key_name,allow_create=False):
        before=load_settings(self.config)
        ident=before.get('tunnel_id','')
        if not ID_PATTERN.fullmatch(ident):raise PreparationFailure('TUNNEL_NOT_FOUND')
        if before.get('key_source','keyring')!='keyring':raise PreparationFailure('KEY_SOURCE_UNSUPPORTED')
        backend=self.store();credential_probe(backend)
        pending=self.read_journal()
        old=backend.get_password(APP,ident)
        if old:
            # Reuse only our own matching creation receipt; do not assume a key
            # found in a store has least privilege. This is historical proof,
            # not a claim of fresh inspection of externally editable permissions.
            receipt=(pending.get('state')=='key_saved' and pending.get('tunnel_id')==ident and
                pending.get('key_name')==key_name and pending.get('permissions')==['Read','Use'] and
                pending.get('credential_fingerprint')==hashlib.sha256(old.encode()).hexdigest())
            result=verify_read(before,backend)
            return {'ok':receipt and result.get('read_authentication')=='passed','stage':'submit-key',
                'key':'reused' if receipt else 'already_cached','key_readback':True,
                'permission_verification':'saved_creation_receipt' if receipt else 'not_checked',
                'live_permission_verification':'not_checked',
                'remediation':'已保存的创建证据不是当前权限自省；外部修改过权限或无对应记录时需核查网页，不自动覆盖或重建。',
                'credentials_returned':False,**result}
        with self.browser_factory() as b:
            page=PlatformPage(b);page.open(KEYS)
            value=None
            if pending.get('state')=='key_creation_pending':
                if pending.get('tunnel_id')!=ident or pending.get('key_name')!=key_name:
                    raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
                try:value=page.secret(pending.get('ownership'))
                except PreparationFailure:
                    raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN') from None
            else:
                if pending.get('state','').endswith('_pending'):raise PreparationFailure('CREATION_OUTCOME_UNCERTAIN')
                if not allow_create:raise PreparationFailure('CREATE_NOT_AUTHORIZED')
                page.select_permissions()
                if load_settings(self.config)!=before:raise PreparationFailure('CONFIG_CHANGED')
                ownership=secrets.token_hex(16)
                self._journal({'state':'key_creation_pending','tunnel_id':ident,'key_name':key_name,
                    'permissions':['Read','Use'],'ownership':ownership,'created_at':time.time()})
                # From click to keystore readback there is no return to an agent.
                page.submit_key(key_name,ownership)
                for attempt in range(20):
                    try:value=page.secret(ownership);break
                    except PreparationFailure as exc:
                        if exc.code!='KEY_NOT_CAPTURED':raise
                        time.sleep(.25)
                if value is None:raise PreparationFailure('KEY_NOT_CAPTURED')
            try:
                if backend.get_password(APP,ident):raise PreparationFailure('KEY_ALREADY_CACHED')
                backend.set_password(APP,ident,value)
                if backend.get_password(APP,ident)!=value:raise PreparationFailure('KEYSTORE_SAVE_FAILED')
            except Exception:
                raise PreparationFailure('KEYSTORE_SAVE_FAILED') from None
            self._journal({'state':'key_saved','tunnel_id':ident,'key_name':key_name,
                'permissions':['Read','Use'],'credential_fingerprint':hashlib.sha256(value.encode()).hexdigest(),
                'saved_at':time.time()})
            # Leave the popup intact: no screenshots, clipboard, or automated
            # closing before storage is certain. Re-running will reuse cache.
        result=verify_read(before,backend)
        return {'ok':result.get('read_authentication')=='passed','stage':'submit-key',
            'key':'saved','key_readback':True,'permissions_verified_before_create':True,
            'credentials_returned':False,**result}

    def run(self,stage,*,name=APP,key_name=APP+'-runtime',allow_create=False,confirm_target=False):
        try:
            if self.config.is_symlink():raise PreparationFailure('UNSAFE_STATE_PATH')
            if self.config.exists():
                st=self.config.stat()
                if st.st_nlink!=1 or st.st_size>1024*1024:raise PreparationFailure('UNSAFE_STATE_PATH')
            if stage=='preflight':return self.preflight()
            if stage=='verify':
                result=verify_read(load_settings(self.config),self.store())
                return {'ok':result.get('read_authentication')=='passed','stage':stage,'credentials_returned':False,**result}
            with Lease(locations()[2],self.config,'browser_preparation'):
                if stage=='cache-tunnel':return self.bind(name,confirm_target)
                if stage=='submit-tunnel':return self.finish_tunnel(name,allow_create,confirm_target)
                if stage=='submit-key':return self.finish_key(key_name,allow_create)
                if stage=='permissions':
                    with self.browser_factory() as b:
                        page=PlatformPage(b);page.open(KEYS);proof=page.select_permissions()
                        return {'ok':True,'stage':stage,**proof,'cloud_mutations':False,'credentials_returned':False}
                raise PreparationFailure('PREPARATION_STAGE_UNSUPPORTED')
        except Exception as exc:
            return failure_payload(exc,stage)
