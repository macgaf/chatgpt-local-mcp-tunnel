"""Tunnel 输出的有界证据投影；不保存自由文本、头、URL 或负载。"""
from __future__ import annotations
import hashlib
import json
import re
import shlex
from .errors import redact

LIMIT = 65536
LAYERS = {'unknown', 'http_peer', 'control_plane', 'tunnel', 'mcp', 'tool', 'child_process', 'local_mcp_dispatch'}
OUTCOMES = {'unknown', 'http_rejection_reported', 'http_failure_reported',
            'http_response_reported', 'execution_failure_reported', 'status_reported', 'request_forwarded'}
FORMATS = {'json', 'logfmt', 'text', 'omitted'}
LEVELS = {'DEBUG', 'INFO', 'WARNING', 'ERROR'}
STATES = {'connected', 'disconnected', 'reconnecting', 'ready', 'healthy'}
OPERATIONS = {'tunnel_metadata_fetch', 'control_plane_poll', 'mcp_dispatch'}
REQUEST_IDS = ('request_id', 'rpc_request_id', 'cmd_request_id', 'tunnel_request_id')
NATIVE_HTTP = re.compile(r'(controlplane client: unexpected (?:metadata )?status ([1-5]\d\d))(?::|$)')
# 只接受完整的错误语法，不在任意正文里搜索数字或单词。
HTTP = re.compile(r'(?i)(?:HTTP(?:/\d(?:\.\d)?)?\s+([1-5]\d\d)(?:\s+(?:Unauthorized|Forbidden|Not Found|Internal Server Error|Bad Gateway|Service Unavailable|Gateway Timeout|OK))?|([1-5]\d\d)\s+(?:Unauthorized|Forbidden)|(?:unexpected (?:HTTP )?status(?: code)?|HTTP (?:response )?status(?: code)?)\s*[:=]?\s*([1-5]\d\d))')
NETWORK = {
    'DNS error': 'DNS_FAILURE', 'DNS resolve error': 'DNS_FAILURE',
    'failed to resolve': 'DNS_FAILURE', 'TLS error': 'TLS_FAILURE',
    'TLS certificate failed': 'TLS_FAILURE', 'connection refused': 'CONNECTION_REFUSED',
    'connection reset by peer': 'CONNECTION_RESET', 'context deadline exceeded': 'NETWORK_TIMEOUT',
    'EOF': 'UNEXPECTED_EOF',
}
NETWORK_LOWER = {k.lower(): v for k, v in NETWORK.items()}


def fingerprint(value):
    return 'sha256:' + hashlib.sha256(str(value).encode('utf-8', 'replace')).hexdigest()


def _unique(pairs):
    obj = dict(pairs)
    if len(obj) != len(pairs):
        raise ValueError('duplicate log fields')
    return obj


def _error(text):
    if not isinstance(text, str) or len(text) > 256:
        return None, None, None
    text = text.strip()
    match = HTTP.fullmatch(text)
    if match:
        status = int(next(g for g in match.groups() if g))
        return status, None, text
    native = NATIVE_HTTP.fullmatch(text)
    if native:
        return int(native[2]), None, text
    if text.lower() in NETWORK_LOWER:
        return None, NETWORK_LOWER[text.lower()], text
    return None, None, None


def safe_diagnostic(value):
    """写入、查看及导出使用同一白名单，拒绝伪造日志中的自由文本。"""
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, allowed in (('format', FORMATS), ('last_reached_layer', LAYERS),
                         ('outcome', OUTCOMES), ('reported_level', LEVELS), ('reported_state', STATES),
                         ('operation', OPERATIONS)):
        if isinstance(value.get(key), str) and value[key] in allowed:
            result[key] = value[key]
    for key in tuple(k+'_hash' for k in REQUEST_IDS)+('line_sha256',):
        v = value.get(key)
        if isinstance(v, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', v):
            result[key] = v
    for key in ('http_status', 'exit_code', 'bytes'):
        v = value.get(key)
        if type(v) is int and ((100 <= v <= 599) if key == 'http_status' else (-2147483648 <= v <= 2147483647)):
            result[key] = v
    for key in ('content_omitted', 'truncated', 'conflicting_status'):
        if type(value.get(key)) is bool:
            result[key] = value[key]
    original = value.get('original_error')
    if _error(original)[2] is not None:
        result['original_error'] = original.strip()
    # 明确写出证据边界，不能把推断当成原始错误。
    result['unconfirmed'] = ['cross_layer_correlation' if any(k in result for k in ('request_id_hash','tunnel_request_id_hash')) else 'request_identity',
                             'root_cause', 'downstream_execution']
    if 'original_error' not in result:
        result['unconfirmed'].append('original_error_text_omitted')
    if result.get('conflicting_status'):
        result['unconfirmed'].append('conflicting_status_fields')
    return result


def diagnostic(text, secrets=()):
    text = redact(text, secrets)
    result = {'format': 'text', 'last_reached_layer': 'unknown', 'outcome': 'unknown',
              'line_sha256': fingerprint(text), 'bytes': len(text.encode('utf-8')),
              'content_omitted': True, 'truncated': len(text.encode('utf-8')) > LIMIT}
    if result['truncated']:
        result['format'] = 'omitted'
        return safe_diagnostic(result)
    raw = text.strip()
    obj = None
    if raw.startswith('{'):
        try:
            obj = json.loads(raw, object_pairs_hook=_unique)
        except (ValueError, RecursionError):
            pass
        if isinstance(obj, dict):
            result['format'] = 'json'
        else:
            return safe_diagnostic(result)
    elif re.match(r'^(?:time|timestamp|level|msg|message|http_status|status_code)=', raw):
        try:
            pairs = [part.split('=', 1) for part in shlex.split(raw)]
            if all(len(p)==2 for p in pairs) and len({p[0] for p in pairs})==len(pairs):
                obj = dict(pairs)
                result['format'] = 'logfmt'
        except ValueError:
            pass
        if obj is None:
            return safe_diagnostic(result)
    status, code, original = None, None, None
    if isinstance(obj, dict):
        attrs = obj.get('attrs')
        fields = {**(attrs if isinstance(attrs, dict) else {}), **obj}
        for name in REQUEST_IDS:
            if isinstance(fields.get(name), (str, int)) and not isinstance(fields[name], bool):
                if fields[name] not in ('', 'missing_request_id', '[REDACTED]'):
                    result[name+'_hash'] = fingerprint(fields[name])
        level = str(fields.get('level', 'INFO')).upper()
        result['reported_level'] = 'WARNING' if level == 'WARN' else level
        layer = fields.get('layer', fields.get('component'))
        if layer == 'controlplane':
            layer = 'control_plane'
        if isinstance(layer, str) and layer in LAYERS:
            result['last_reached_layer'] = layer
        # 只读明确的 HTTP 状态字段；业务 status 和嵌套 body/error.status 不作推断。
        statuses = []
        for name in ('http_status', 'status_code'):
            v = fields.get(name)
            if result['format']=='logfmt' and isinstance(v, str) and re.fullmatch(r'[1-5]\d\d', v):
                v = int(v)
            if type(v) is int and 100 <= v <= 599:
                statuses.append(v)
        if len(set(statuses)) > 1:
            result['conflicting_status'] = True
            return safe_diagnostic(result)
        if statuses:
            status = statuses[0]
        # error 必须整体符合已知错误语法；msg 只识别已知状态，不解析正文。
        error_text = fields.get('error')
        if fields.get('component') == 'controlplane' and isinstance(error_text,str):
            # 原生错误会在状态码后拼接 HTTP 响应正文；只保留固定语法前缀。
            prefix = NATIVE_HTTP.match(error_text[:100])
            if prefix:
                error_text = prefix[1]
        error_status, code, original = _error(error_text)
        if status is None:
            status = error_status
        elif error_status is not None and error_status != status:
            original = None  # 冲突字段不混用成同一次请求的证据。
        state = fields.get('msg', fields.get('message'))
        if fields.get('component') == 'controlplane':
            operation = {'tunnel metadata fetch failed':'tunnel_metadata_fetch',
                         'poll failed; backing off':'control_plane_poll'}.get(state) if isinstance(state,str) else None
            if operation:
                result['operation'] = operation
        if (fields.get('component') == 'dispatcher' and isinstance(state,str) and
                state.lower() == 'dispatcher forwarded command to mcp server'):
            result['last_reached_layer'] = 'local_mcp_dispatch'
            result['outcome'] = 'request_forwarded'
            result['operation'] = 'mcp_dispatch'
        if isinstance(state, str) and state.lower() in STATES:
            result['reported_state'] = state.lower()
        exit_code = fields.get('exit_code')
        if result['format']=='logfmt' and isinstance(exit_code, str) and re.fullmatch(r'-?\d{1,10}', exit_code):
            exit_code = int(exit_code)
        if type(exit_code) is int:
            result['exit_code'] = exit_code
            if exit_code:
                result['outcome'] = 'execution_failure_reported'
    else:
        status, code, original = _error(raw)
        if raw.lower() in STATES:
            result['reported_state'] = raw.lower()
    if status is not None:
        result['http_status'] = status
        result['outcome'] = ('http_rejection_reported' if status in (401,403) else
                             'http_failure_reported' if status >= 400 else 'http_response_reported')
        if result['last_reached_layer'] == 'unknown':
            result['last_reached_layer'] = 'http_peer'
    if original:
        result['original_error'] = original
    if result.get('reported_state') and result['outcome']=='unknown':
        result['outcome'] = 'status_reported'
    return safe_diagnostic(result)


def error_code(evidence):
    status = evidence.get('http_status')
    if status == 401:
        return 'TUNNEL_AUTHENTICATION_FAILED'
    if status == 403:
        return 'TUNNEL_PERMISSION_DENIED'
    if type(status) is int:
        return 'TUNNEL_HTTP_FAILED' if status >= 400 else None
    return NETWORK_LOWER.get(str(evidence.get('original_error', '')).lower())
