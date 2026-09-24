"""Best-effort recoverable, cross-file exact replacement batches (not filesystem transactions)."""
from __future__ import annotations
from contextlib import ExitStack
import difflib
import json
import os
import uuid
from .errors import Fault, normalize_error
from .storage import Lease, commit_bytes, digest, expected_matches, private_dir, read_bytes, write_private


def apply_changes(service, changes, dry_run=False):
    policy = service.policy
    if not isinstance(changes,list) or not 1 <= len(changes) <= 64:
        raise ValueError('changes must contain 1..64 entries')
    paths = []
    for i,c in enumerate(changes):
        if not isinstance(c,dict) or set(c)-{'path','relative_path','old_text','new_text','expected_sha256'}:
            raise ValueError(f'changes[{i}] has unsupported fields')
        if ('path' in c) == ('relative_path' in c):
            raise ValueError('each change requires exactly one path or relative_path')
        if not all(isinstance(c.get(k),str) for k in ('old_text','new_text','expected_sha256')):
            raise ValueError('old_text, new_text and original expected_sha256 are required strings')
        if not c['old_text']:
            raise Fault('AMBIGUOUS_EDIT','old_text 不能为空。','缺少唯一匹配目标。','提供唯一原文上下文。')
        paths.append(policy.require(c.get('path',c.get('relative_path')),write=True))
    service.commands.guard_mutation(paths)
    canonical = sorted(set(paths),key=lambda p:os.path.normcase(str(p)))
    transaction_id = uuid.uuid4().hex
    with ExitStack() as locks:
        for p in canonical:
            locks.enter_context(Lease(policy.state_dir,p,'apply_patch',transaction_id))
        original,updated,expected={}, {}, {}
        total=0
        for p in canonical:
            original[p]=read_bytes(policy,str(p))[1]
            if b'\0' in original[p]:
                raise ValueError('apply_patch requires UTF-8 text files')
            updated[p]=original[p].decode('utf-8')
            total+=len(original[p])
        if total>policy.max_patch_bytes:
            raise Fault('PATCH_BUDGET_EXCEEDED','整批原文件超过预算。',str(total),
                        '拆分补丁或缩小修改范围。',max_bytes=policy.max_patch_bytes)
        for i,(c,p) in enumerate(zip(changes,paths)):
            expected_matches(original[p],c['expected_sha256'])
            if p in expected and expected[p]!=c['expected_sha256']:
                raise ValueError('all changes for a path must guard the same original file hash')
            expected[p]=c['expected_sha256']
            text=updated[p]
            first=text.find(c['old_text'])
            if first<0 or text.find(c['old_text'],first+1)>=0:
                raise Fault('AMBIGUOUS_EDIT','补丁目标必须恰好出现一次。','零次或多次匹配。',
                            '读取最新文件并使用唯一上下文；本批次尚未写入。',change_index=i,path=policy.relative(p))
            updated[p]=text.replace(c['old_text'],c['new_text'],1)
        bodies={p:s.encode('utf-8') for p,s in updated.items()}
        if (sum(map(len,bodies.values()))>policy.max_patch_bytes or
                any(len(b)>policy.max_file_size for b in bodies.values())):
            raise Fault('PATCH_BUDGET_EXCEEDED','整批结果或单文件超过预算。','写入前校验失败。','拆分修改。')
        previews=[]
        remaining=policy.max_text_output_bytes
        for p in canonical:
            diff=''.join(difflib.unified_diff(original[p].decode().splitlines(True),updated[p].splitlines(True),
                                             fromfile=policy.relative(p),tofile=policy.relative(p)))
            raw=diff.encode();small=raw[:remaining].decode('utf-8','ignore');remaining-=len(small.encode())
            previews.append({'path':policy.relative(p),'before_sha256':digest(original[p]),
                'after_sha256':digest(bodies[p]),'changed':original[p]!=bodies[p],
                'diff':small,'diff_truncated':len(raw)>len(small.encode())})
        if dry_run:
            return {'ok':True,'dry_run':True,'file_count':len(canonical),'change_count':len(changes),'files':previews}
        journal=private_dir(policy.state_dir/'transactions')/(transaction_id+'.json')
        def record(state, **kw):
            data={'transaction_id':transaction_id,'state':state,'root':str(policy.root),
                  'files':[{k:v for k,v in f.items() if k not in ('diff','diff_truncated')} for f in previews],**kw}
            tmp=journal.with_name(journal.name+'.'+uuid.uuid4().hex+'.tmp')
            write_private(tmp,json.dumps(data,ensure_ascii=False).encode());os.replace(tmp,journal)
        record('prepared')
        applied=[]
        attempted=[]
        try:
            # All preconditions must still hold immediately before the first write.
            for p in canonical:
                expected_matches(read_bytes(policy,str(p))[1],expected[p])
            for p in canonical:
                attempted.append(p)
                result=commit_bytes(policy,p,bodies[p],original[p],expected[p])
                applied.append((p,result))
                record('applying',applied=[r for _,r in applied])
            record('committed',applied=[r for _,r in applied])
        except Exception as exc:
            rollback=[]
            # A post-write failure may have committed the currently failing file.
            for p in reversed(attempted):
                try:
                    current=read_bytes(policy,str(p))[1]
                    if current==original[p]:
                        rollback.append({'path':policy.relative(p),'status':'unchanged'})
                    elif current==bodies[p]:
                        commit_bytes(policy,p,original[p],current,digest(current))
                        rollback.append({'path':policy.relative(p),'status':'restored'})
                    else:
                        rollback.append({'path':policy.relative(p),'status':'external_change_not_overwritten',
                                         'current_sha256':digest(current)})
                except Exception as rollback_error:
                    rollback.append({'path':policy.relative(p),'status':'restore_failed',
                                     'error':normalize_error(rollback_error).payload()['error']})
            incomplete=any(x['status'] not in ('restored','unchanged') for x in rollback)
            try:record('rollback_incomplete' if incomplete else 'rolled_back',rollback=rollback)
            except OSError:pass
            raise Fault('PATCH_ROLLBACK_INCOMPLETE' if incomplete else 'PATCH_FAILED_ROLLED_BACK',
                        '跨文件补丁失败，已逐文件检查恢复结果。', normalize_error(exc).payload()['error'],
                        '查看 rollback 和 list_backups；不覆盖外部新修改。',
                        transaction_id=transaction_id,rollback=rollback,
                        atomic_across_files=False,crash_atomic=False) from exc
        return {'ok':True,'transaction_id':transaction_id,'file_count':len(canonical),
                'change_count':len(changes),'files':[r for _,r in applied],
                'changed':any(r.get('changed') for _,r in applied),
                'atomic_across_files':False,'crash_atomic':False}
