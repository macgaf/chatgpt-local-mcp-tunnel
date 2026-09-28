"""Capability evidence from this runtime, never an assertion about the ChatGPT catalog."""
from __future__ import annotations
import hashlib
import json
from . import __version__


def capability_summary(service):
    # One registry and one enablement predicate for both diagnostics and tools/list.
    from .server import DESCRIPTIONS, Protocol, tool_disabled_reason
    specs = Protocol(service).specs
    tools = [specs[name] for name in sorted(specs)]
    fingerprint = hashlib.sha256(json.dumps(tools, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False).encode('utf-8')).hexdigest()
    return {
        'server_version': __version__,
        'runtime_instance': service.runtime_instance,
        'file_write_enabled': 'write_file' in specs,
        'git_read_enabled': 'git_status' in specs,
        'git_branch_create_enabled': 'git_create_branch' in specs,
        'git_branch_switch_enabled': 'git_switch_branch' in specs,
        'shell_enabled': 'run_command' in specs,
        'codex_history_enabled': 'save_conversation_to_codex' in specs,
        'git_push_enabled': 'git_push' in specs,
        'write_scope_semantics': 'restricted_write_roots' if service.policy.write_roots else 'root_minus_denies',
        'tool_count': len(specs),
        'tool_names': sorted(specs),
        'tool_catalog_sha256': fingerprint,
        'disabled_tools': [{'name': name, 'reason': tool_disabled_reason(name, service.policy)}
                           for name in sorted(DESCRIPTIONS) if name not in specs],
        'git_supported_layouts': ['standard_git_directory', 'standard_git_directory_with_worktree_config', 'linked_worktree_gitfile'],
        'git_unsupported_layouts': ['submodule_gitfile', 'external_object_store'],
        'path_checks_required': True,
        'client_tool_visibility_verified': False,
        'config_reload': 'restart_required',
        'note': '本机策略与工具注册证据，不证明 ChatGPT 已刷新工具。Shell 关闭不等于文件只读；Git 布局失败不等于文件不可写。',
    }
