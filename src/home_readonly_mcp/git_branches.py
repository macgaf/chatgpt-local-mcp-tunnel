"""Local branch operations with no shell, force, remote guessing or arbitrary revisions."""
from __future__ import annotations
import re
from .errors import Fault
from .git_layout import layout


class BranchActions:
    def _branch_name(self, name):
        # Do not accept checkout shorthand (@{-1}), flags, refspecs or pathspecs.
        if (not isinstance(name, str) or name == 'HEAD' or
                not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,199}', name)):
            raise Fault('INVALID_BRANCH_NAME', '分支名无效。', '需要 1–200 位安全的本地分支名。',
                        '使用例如 fix/security；不接受 flags、HEAD、@{-1} 或任意 revision。')
        control = self.policy.state_dir / 'git-control'
        code, _ = self.run(control, ['check-ref-format', 'refs/heads/' + name], allow_failure=True)
        if code:
            raise Fault('INVALID_BRANCH_NAME', '分支名不符合 Git 规则。', 'check-ref-format rejected the name',
                        '使用例如 fix/security，避免 ..、.lock 或空路径段。')
        return name

    def _head_info(self, repo):
        code, value = self.run(repo, ['symbolic-ref', '--quiet', 'HEAD'], allow_failure=True)
        if code not in (0, 1):
            raise Fault('GIT_HEAD_INVALID', '无法读取 HEAD。', 'symbolic-ref failed', '在本机检查仓库完整性。')
        ref = value.decode('utf-8', 'strict').strip() if code == 0 else ''
        if ref and not ref.startswith('refs/heads/'):
            raise Fault('GIT_HEAD_INVALID', 'HEAD 不是本地分支。', 'unsupported symbolic reference',
                        '在本机检查 HEAD；不自动改写。')
        code, value = self.run(repo, ['rev-parse', '--verify', 'HEAD^{commit}'], allow_failure=True)
        return {'branch': ref[len('refs/heads/'):] if ref else None,
                'head': value.decode('ascii', 'strict').strip() if code == 0 else None,
                'detached_head': not bool(ref), 'unborn_head': code != 0}

    def _clean_branch_state(self, repo, expected_head=None):
        gitdir, common = layout(self.policy, repo)
        markers = ('MERGE_HEAD', 'CHERRY_PICK_HEAD', 'REVERT_HEAD', 'REBASE_HEAD',
                   'rebase-apply', 'rebase-merge', 'sequencer', 'BISECT_LOG')
        if any((gitdir / name).exists() for name in markers):
            raise Fault('GIT_OPERATION_IN_PROGRESS', '仓库有尚未完成的 Git 操作。',
                        'merge/rebase/cherry-pick/revert/bisect state is present',
                        '先在本机完成或取消原操作；不会自动 abort、stash 或 reset。')
        if any((base / name).exists() for base in {gitdir, common}
               for name in ('index.lock', 'HEAD.lock', 'packed-refs.lock')):
            raise Fault('GIT_LOCKED', 'Git 索引或引用锁被占用。', 'existing Git lock',
                        '检查持锁进程；不会自动删除锁。', retryable=True, holder='unknown')
        info = self._head_info(repo)
        if info['unborn_head'] or info['detached_head']:
            raise Fault('GIT_BRANCH_STATE_UNSUPPORTED', '分支操作需要已有提交的本地分支。',
                        'unborn or detached HEAD', '在本机完成首个提交或恢复本地分支。')
        if expected_head is not None:
            if not isinstance(expected_head, str) or not re.fullmatch(r'[0-9a-fA-F]{40}|[0-9a-fA-F]{64}', expected_head):
                raise ValueError('expected_head must be a full commit SHA')
            if expected_head.lower() != info['head']:
                raise Fault('GIT_HEAD_CHANGED', 'HEAD 已改变，未执行分支修改。', 'expected_head mismatch',
                            '重新读取 git_status 并核查并发修改，不自动刷新预期值。')
        # Never let status recurse into a submodule whose Git config was not audited.
        _, staged = self.run(repo, ['ls-files', '--stage', '-z'])
        if any(record.startswith(b'160000 ') for record in staged.split(b'\0')):
            raise Fault('GIT_SUBMODULE_UNSUPPORTED', '分支操作不支持含子模块的索引。',
                        'gitlink present in current index',
                        '在本机审查子模块并切换；不会调用其 Git 配置或递归检出。')
        _, body = self.run(repo, ['status', '--porcelain=v1', '-z', '--untracked-files=all',
                                 '--ignore-submodules=all'])
        if body:
            # Do not expose filenames here: even a denied/untracked secret must block switching.
            raise Fault('GIT_DIRTY_WORKTREE', '工作区或暂存区不干净，未执行分支修改。',
                        'tracked, staged or untracked changes exist',
                        '先处理已有修改；不会自动 stash、reset、clean 或覆盖。')
        _, entries = self.run(repo, ['ls-files', '-v', '-z'])
        if any(item and (item[:1] == b'S' or item[:1].islower()) for item in entries.split(b'\0')):
            raise Fault('GIT_INDEX_FLAGS_UNSUPPORTED', '索引含隐藏工作区变化的标记。',
                        'skip-worktree or assume-unchanged entries',
                        '在本机审查稀疏检出/索引标记后再切换；不会自动修改这些标记。')
        return info

    def _local_branch_exists(self, repo, name):
        code, _ = self.run(repo, ['show-ref', '--verify', '--quiet', 'refs/heads/' + name], allow_failure=True)
        if code not in (0, 1):
            raise Fault('GIT_REF_INVALID', '无法检查本地分支。', 'show-ref failed', '在本机检查引用完整性。')
        return code == 0

    def _checkout_paths(self, repo, before, after):
        names = self.names(repo, ['diff', '--name-only', '--no-renames', '--no-ext-diff',
                                 '--no-textconv', '--ignore-submodules=none', before, after])
        self.safe_paths(repo, names, write=True, strict=True)
        if sum(len(name.encode('utf-8')) + 1 for name in names) > 24000:
            raise Fault('GIT_PATH_BUDGET', '分支切换影响路径过多。', 'checkout path budget exceeded',
                        '在本机审查并切换；不会部分检出。')
        if not names:
            return
        # Inspect blobs before materializing them. Files currently absent still obey policy.
        _, body = self.run(repo, ['ls-tree', '-r', '-l', '-z', '--full-tree', after, '--', *names])
        for record in body.split(b'\0'):
            if not record:
                continue
            fields = record.split(b'\t', 1)[0].split()
            if (len(fields) != 4 or fields[0] not in (b'100644', b'100755') or
                    fields[1] != b'blob' or not fields[3].isdigit() or
                    int(fields[3]) > self.policy.max_file_size):
                raise Fault('GIT_CHECKOUT_PATH_DENIED', '目标分支含不允许检出的对象。',
                            'symlink, submodule, oversized blob or unsupported object',
                            '在本机审查目标树；不跳过文件策略或自动展开子模块。')

    def branches(self, repo_path='.', offset=0, limit=100):
        if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= 500:
            raise ValueError('offset >=0 and limit 1..500 required')
        with self.operation(repo_path) as (repo, _):
            info = self._head_info(repo)
            _, body = self.run(repo, ['for-each-ref', '--sort=refname',
                                     '--format=%(refname)%00%(objectname)', 'refs/heads/'])
            rows = []
            for record in body.decode('utf-8', 'strict').splitlines():
                ref, sha = record.split('\0')
                name = ref[len('refs/heads/'):]
                rows.append({'name': name, 'sha': sha, 'current': name == info['branch']})
            selected = rows[offset:offset + limit]
            more = offset + len(selected) < len(rows)
            return {'ok': True, **info, 'branches': selected, 'total': len(rows),
                    'next_offset': offset + len(selected) if more else None,
                    'has_more': more, 'snapshot': False}

    def create_branch(self, branch, repo_path='.', checkout=True, expected_head=None):
        if type(checkout) is not bool:
            raise ValueError('checkout must be boolean')
        with self.operation(repo_path, write=True) as (repo, _):
            branch = self._branch_name(branch)
            before = self._clean_branch_state(repo, expected_head)
            if self._local_branch_exists(repo, branch):
                raise Fault('GIT_BRANCH_EXISTS', '目标分支已存在。', 'local branch already exists',
                            '核查后使用 git_switch_branch；不会重置或覆盖已有分支。')
            if checkout:
                self.run(repo, ['checkout', '--no-guess', '--no-overwrite-ignore', '-b', branch, before['head']])
            else:
                self.run(repo, ['branch', '--no-track', '--', branch, before['head']])
            after = self._head_info(repo)
            if after['head'] != before['head'] or after['branch'] != (branch if checkout else before['branch']):
                raise Fault('GIT_POSTCONDITION_FAILED', '分支操作后的状态与预期不一致。',
                            'possible concurrent Git operation; branch may have been created',
                            '停止并检查实际状态；不会覆盖并发修改或自动重试。')
            return {'ok': True, 'created': True, 'branch': branch, 'checked_out': checkout,
                    'previous_branch': before['branch'], 'head': after['head']}

    def switch_branch(self, branch, repo_path='.', expected_head=None):
        with self.operation(repo_path, write=True) as (repo, _):
            branch = self._branch_name(branch)
            before = self._clean_branch_state(repo, expected_head)
            if not self._local_branch_exists(repo, branch):
                raise Fault('GIT_BRANCH_NOT_FOUND', '本地分支不存在。', 'no matching local branch',
                            '先 git_create_branch；不会猜测远端或自动 fetch。')
            if branch == before['branch']:
                return {'ok': True, 'switched': False, **before}
            _, target = self.run(repo, ['rev-parse', '--verify', 'refs/heads/' + branch + '^{commit}'])
            target = target.decode('ascii').strip()
            self._checkout_paths(repo, before['head'], target)
            self.run(repo, ['checkout', '--no-guess', '--no-overwrite-ignore', branch, '--'])
            after = self._head_info(repo)
            if after['branch'] != branch or after['head'] != target:
                raise Fault('GIT_POSTCONDITION_FAILED', '切换后的分支与预期不一致。',
                            'possible concurrent Git operation', '停止并核查；不强制回滚外部修改。')
            return {'ok': True, 'switched': True, 'previous_branch': before['branch'], **after}
