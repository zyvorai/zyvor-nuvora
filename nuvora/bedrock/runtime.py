# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""bedrock-runtime operations: Converse, ConverseStream, InvokeModel(WithResponseStream), CountTokens.

Everything goes through the same Platform pipeline as /v1/chat/completions (`chat`, `open_stream`,
`embed`): input and output guardrails, routing, daily budget, usage ledger, audit. This module only
translates wire shapes. A field Nuvora cannot honour is a ValidationException naming it; nothing is
silently dropped."""
import base64
import binascii
import json
import secrets

from ..security import Fault, require
from ..store import canonical
from . import errors, eventstream as es
from .router import Response, Stream

REFUSAL_TEXT = 'The request or the response was blocked by the tenant guardrail policy.'
IMAGE_FORMATS = {'png': 'image/png', 'jpeg': 'image/jpeg', 'webp': 'image/webp'}
CONVERSE_FIELDS = {'messages', 'system', 'inferenceConfig', 'toolConfig', 'guardrailConfig', 'additionalModelRequestFields',
                   'additionalModelResponseFieldPaths', 'promptVariables', 'requestMetadata', 'performanceConfig', 'serviceTier'}
UNSUPPORTED_CONVERSE = ('guardrailConfig', 'additionalModelRequestFields', 'additionalModelResponseFieldPaths', 'promptVariables',
                        'requestMetadata', 'performanceConfig', 'serviceTier')
ANTHROPIC_VERSION = 'bedrock-2023-05-31'


# ---- model resolution -------------------------------------------------------------------

def _arn_tail(model_id):
    """(kind, id) for an ARN-ish identifier, else (None, model_id). ARNs are not parsed beyond `<kind>/<id>`."""
    if model_id.startswith('arn:'):
        parts = model_id.split(':', 5)
        resource = parts[5] if len(parts) == 6 else ''
        kind, _, rest = resource.partition('/')
        if not rest:
            raise errors.validation('modelId is not a valid ARN')
        return kind, rest
    return None, model_id


def resolve(req, model_id, capabilities=('chat',)):
    """(value for the internal `model` field, record, is_router). Unknown id is ResourceNotFoundException."""
    app, p = req.app, req.principal
    if not isinstance(model_id, str) or not model_id:
        raise errors.validation('modelId is required')
    kind, ident = _arn_tail(model_id)
    if kind in ('inference-profile', 'application-inference-profile') or ident.startswith('router:'):
        rid = ident[7:] if ident.startswith('router:') else ident
        try:
            return 'router:' + rid, app.get(p, 'routers', rid), True
        except KeyError:
            raise errors.not_found(f'Could not resolve the inference profile {model_id}: no such router')
    if kind not in (None, 'foundation-model'):
        raise errors.not_found(f'Could not resolve the model {model_id}')
    try:
        record = app.get(p, 'models', ident)
    except KeyError:
        raise errors.not_found(f'Could not resolve the model {model_id}: no such model or router for this tenant')
    if not record.get('enabled'):
        raise errors.validation(f'The model {model_id} is disabled')
    if record.get('capability', 'chat') not in capabilities:
        raise errors.validation(f"The model {model_id} has capability '{record.get('capability', 'chat')}', which this operation does not support")
    return record['id'], record, False


# ---- shared message folding -------------------------------------------------------------

def _data_url(fmt, data, where):
    if not isinstance(data, str):
        raise errors.validation(f'{where}.source.bytes must be a base64 string')
    try:
        base64.b64decode(data, validate=True)
    except (binascii.Error, ValueError):
        raise errors.validation(f'{where}.source.bytes is not valid base64')
    return f'data:{IMAGE_FORMATS[fmt]};base64,{data}'


def _json_text(value):
    return value if isinstance(value, str) else json.dumps(value, separators=(',', ':'), ensure_ascii=False)


def _fold(role, items, where):
    """Items [('text', s) | ('image', url) | ('call', id, name, json) | ('result', id, text)] to internal messages."""
    out = []
    if role == 'assistant':
        if any(i[0] in ('image', 'result') for i in items):
            raise errors.validation(f'{where}: assistant messages can hold only text and tool use')
        calls = [{'id': i[1], 'type': 'function', 'function': {'name': i[2], 'arguments': i[3]}} for i in items if i[0] == 'call']
        message = {'role': 'assistant', 'content': '\n'.join(i[1] for i in items if i[0] == 'text')}
        if calls:
            message['tool_calls'] = calls
        return [message]
    if any(i[0] == 'call' for i in items):
        raise errors.validation(f'{where}: tool use blocks belong on assistant messages')
    for i in items:
        if i[0] == 'result':
            out.append({'role': 'tool', 'tool_call_id': i[1], 'content': i[2]})
    rest = [i for i in items if i[0] in ('text', 'image')]
    if rest:
        if len(rest) == 1 and rest[0][0] == 'text':
            out.append({'role': 'user', 'content': rest[0][1]})
        else:
            out.append({'role': 'user', 'content': [{'type': 'text', 'text': i[1]} if i[0] == 'text' else {'type': 'image_url', 'image_url': {'url': i[1]}} for i in rest]})
    return out


def _check_keys(obj, allowed, where):
    if not isinstance(obj, dict):
        raise errors.validation(f'{where} must be an object')
    extra = sorted(set(obj) - set(allowed))
    if extra:
        raise errors.validation(f"{where}: unsupported field {', '.join(extra)}")


# ---- Converse request mapping -----------------------------------------------------------

def _converse_blocks(role, blocks, where):
    if not isinstance(blocks, list) or not blocks:
        raise errors.validation(f'{where}.content must be a non-empty list')
    items = []
    for n, block in enumerate(blocks):
        at = f'{where}.content[{n}]'
        if not isinstance(block, dict) or len(block) != 1:
            raise errors.validation(f'{at} must hold exactly one content block type')
        (kind, value), = block.items()
        if kind == 'text':
            if not isinstance(value, str):
                raise errors.validation(f'{at}.text must be a string')
            items.append(('text', value))
        elif kind == 'image':
            _check_keys(value, ('format', 'source'), at + '.image')
            if value.get('format') not in IMAGE_FORMATS:
                raise errors.validation(f"{at}.image.format must be one of {', '.join(sorted(IMAGE_FORMATS))} (gif is not supported)")
            source = value.get('source')
            if not isinstance(source, dict) or set(source) != {'bytes'}:
                raise errors.validation(f'{at}.image.source must be {{"bytes": ...}} (s3Location is not supported)')
            items.append(('image', _data_url(value['format'], source['bytes'], at + '.image')))
        elif kind == 'toolUse':
            _check_keys(value, ('toolUseId', 'name', 'input'), at + '.toolUse')
            if not isinstance(value.get('toolUseId'), str) or not isinstance(value.get('name'), str):
                raise errors.validation(f'{at}.toolUse needs toolUseId and name')
            items.append(('call', value['toolUseId'], value['name'], json.dumps(value.get('input') or {}, separators=(',', ':'))))
        elif kind == 'toolResult':
            _check_keys(value, ('toolUseId', 'content', 'status'), at + '.toolResult')
            if not isinstance(value.get('toolUseId'), str) or not isinstance(value.get('content'), list):
                raise errors.validation(f'{at}.toolResult needs toolUseId and content')
            parts = []
            for m, part in enumerate(value['content']):
                if isinstance(part, dict) and set(part) == {'text'} and isinstance(part['text'], str):
                    parts.append(part['text'])
                elif isinstance(part, dict) and set(part) == {'json'}:
                    parts.append(_json_text(part['json']))
                else:
                    raise errors.validation(f"{at}.toolResult.content[{m}]: only text and json blocks are supported")
            if value.get('status') not in (None, 'success', 'error'):
                raise errors.validation(f'{at}.toolResult.status must be success or error')
            text = '\n'.join(parts) or ' '
            items.append(('result', value['toolUseId'], ('Tool error: ' + text) if value.get('status') == 'error' else text))
        else:
            raise errors.validation(f'{at}: content block type "{kind}" is not supported (supported: text, image, toolUse, toolResult)')
    return items


def _converse_tools(config):
    _check_keys(config, ('tools', 'toolChoice'), 'toolConfig')
    tools = config.get('tools')
    if not isinstance(tools, list) or not tools:
        raise errors.validation('toolConfig.tools must be a non-empty list')
    out = []
    for n, tool in enumerate(tools):
        if not isinstance(tool, dict) or set(tool) != {'toolSpec'}:
            raise errors.validation(f'toolConfig.tools[{n}] must be {{"toolSpec": ...}} (systemTool and cachePoint are not supported)')
        spec = tool['toolSpec']
        _check_keys(spec, ('name', 'description', 'inputSchema', 'strict'), f'toolConfig.tools[{n}].toolSpec')
        if spec.get('strict'):
            raise errors.validation(f'toolConfig.tools[{n}].toolSpec.strict is not supported')
        schema = spec.get('inputSchema')
        if not isinstance(schema, dict) or set(schema) != {'json'} or not isinstance(schema['json'], dict):
            raise errors.validation(f'toolConfig.tools[{n}].toolSpec.inputSchema must be {{"json": {{...}}}}')
        function = {'name': spec.get('name'), 'parameters': schema['json']}
        if spec.get('description'):
            function['description'] = spec['description']
        out.append({'type': 'function', 'function': function})
    choice = config.get('toolChoice')
    mapped = None
    if choice is not None:
        if not isinstance(choice, dict) or len(choice) != 1:
            raise errors.validation('toolConfig.toolChoice must hold exactly one of auto, any, tool')
        (kind, value), = choice.items()
        if kind == 'auto':
            mapped = 'auto'
        elif kind == 'any':
            mapped = 'required'
        elif kind == 'tool' and isinstance(value, dict) and isinstance(value.get('name'), str):
            mapped = {'type': 'function', 'function': {'name': value['name']}}
        else:
            raise errors.validation('toolConfig.toolChoice must be {"auto":{}}, {"any":{}} or {"tool":{"name":...}}')
    return out, mapped


def _generation(config):
    out = {}
    if config is None:
        return out
    _check_keys(config, ('maxTokens', 'temperature', 'topP', 'stopSequences'), 'inferenceConfig')
    for src, dst, kinds in (('maxTokens', 'max_tokens', int), ('temperature', 'temperature', (int, float)), ('topP', 'top_p', (int, float)), ('stopSequences', 'stop', list)):
        if src in config:
            value = config[src]
            if isinstance(value, bool) or not isinstance(value, kinds):
                raise errors.validation(f'inferenceConfig.{src} has the wrong type')
            out[dst] = value
    return out


def converse_to_chat(request, model_value):
    """A Converse request body to the internal chat body."""
    _check_keys(request, CONVERSE_FIELDS, 'request')
    for name in UNSUPPORTED_CONVERSE:
        if request.get(name) not in (None, {}, []):
            hint = ' (guardrails are applied from the tenant policy; per-request guardrails arrive with the guardrail resources)' if name == 'guardrailConfig' else ''
            raise errors.validation(f'{name} is not supported by this Nuvora release{hint}')
    messages = []
    system = request.get('system')
    if system is not None:
        if not isinstance(system, list):
            raise errors.validation('system must be a list')
        for n, block in enumerate(system):
            if not isinstance(block, dict) or set(block) != {'text'} or not isinstance(block['text'], str):
                raise errors.validation(f'system[{n}]: only text blocks are supported (guardContent and cachePoint are not)')
            messages.append({'role': 'system', 'content': block['text']})
    source = request.get('messages')
    if not isinstance(source, list) or not source:
        raise errors.validation('messages must be a non-empty list')
    for n, message in enumerate(source):
        where = f'messages[{n}]'
        _check_keys(message, ('role', 'content'), where)
        if message.get('role') not in ('user', 'assistant'):
            raise errors.validation(f'{where}.role must be user or assistant')
        messages.extend(_fold(message['role'], _converse_blocks(message['role'], message.get('content'), where), where))
    body = {'model': model_value, 'messages': messages, **_generation(request.get('inferenceConfig'))}
    if request.get('toolConfig') is not None:
        body['tools'], choice = _converse_tools(request['toolConfig'])
        if choice is not None:
            body['tool_choice'] = choice
    return body


def stop_reason(calls, completion_tokens, max_tokens):
    """Nuvora providers do not report why generation ended, so this is derived: tool calls, a completion
    that used the whole budget, otherwise a normal end. `stop_sequence` and `content_filtered` are never reported."""
    if calls:
        return 'tool_use'
    return 'max_tokens' if max_tokens and completion_tokens >= max_tokens else 'end_turn'


def _refusal(exc):
    return exc.status == 422 and 'refused by guardrail' in str(exc)


def _usage(result):
    usage = result.get('usage') or {}
    inp, out = int(usage.get('prompt_tokens', 0)), int(usage.get('completion_tokens', 0))
    return {'inputTokens': inp, 'outputTokens': out, 'totalTokens': inp + out}


def _tool_use_blocks(calls):
    blocks = []
    for call in calls or []:
        try:
            arguments = json.loads(call['function'].get('arguments') or '{}')
        except ValueError:
            arguments = {}
        blocks.append({'toolUse': {'toolUseId': call['id'], 'name': call['function']['name'], 'input': arguments}})
    return blocks


def converse(req):
    require(req.principal, 'developer', 'admin')
    request = req.json()
    value, record, is_router = resolve(req, req.params['modelId'])
    body = converse_to_chat(request, value)
    try:
        result = req.app.chat(req.principal, body)
    except Fault as exc:
        if not _refusal(exc):
            raise
        return Response({'output': {'message': {'role': 'assistant', 'content': [{'text': REFUSAL_TEXT}]}}, 'stopReason': 'guardrail_intervened',
                         'usage': {'inputTokens': 0, 'outputTokens': 0, 'totalTokens': 0}, 'metrics': {'latencyMs': 0}})
    calls = result.get('tool_calls') or []
    content = ([{'text': result['content']}] if result['content'] else []) + _tool_use_blocks(calls)
    reason = stop_reason(calls, result['usage'].get('completion_tokens', 0), body.get('max_tokens', 1024))
    return Response({'output': {'message': {'role': 'assistant', 'content': content or [{'text': ''}]}}, 'stopReason': reason,
                     'usage': _usage(result), 'metrics': {'latencyMs': int(result.get('latency_ms', 0))}},
                    headers={'X-Nuvora-Evidence-Class': str(result.get('evidence_class', ''))})


# ---- streaming --------------------------------------------------------------------------

def neutral(events):
    """Platform stream events to ('text', s) | ('calls', [...]) | ('refused',) | ('done', info). A mid-stream
    guardrail refusal ends the stream cleanly; any other Fault propagates (an exception frame)."""
    try:
        for item in events:
            kind = item.get('event')
            if kind == 'delta':
                yield 'text', item['text']
            elif kind == 'tool_calls':
                yield 'calls', item['calls']
            elif kind == 'done':
                yield 'done', item
    except Fault as exc:
        if not _refusal(exc):
            raise
        yield 'refused', None
    finally:
        events.close()


def converse_frames(events, max_tokens):
    j = es.json_event
    yield j('messageStart', {'role': 'assistant'})
    index, open_text, reason, info, calls_seen = -1, False, 'end_turn', {}, False
    for kind, value in events:
        if kind == 'text':
            if not open_text:
                index, open_text = index + 1, True
            yield j('contentBlockDelta', {'contentBlockIndex': index, 'delta': {'text': value}})
        elif kind == 'calls':
            if open_text:
                yield j('contentBlockStop', {'contentBlockIndex': index})
                open_text = False
            calls_seen = True
            for block in _tool_use_blocks(value):
                index += 1
                use = block['toolUse']
                yield j('contentBlockStart', {'contentBlockIndex': index, 'start': {'toolUse': {'toolUseId': use['toolUseId'], 'name': use['name']}}})
                yield j('contentBlockDelta', {'contentBlockIndex': index, 'delta': {'toolUse': {'input': json.dumps(use['input'], separators=(',', ':'))}}})
                yield j('contentBlockStop', {'contentBlockIndex': index})
        elif kind == 'refused':
            if not open_text:
                index, open_text = index + 1, True
            yield j('contentBlockDelta', {'contentBlockIndex': index, 'delta': {'text': REFUSAL_TEXT}})
            reason = 'guardrail_intervened'
        else:
            info = value
    if open_text:
        yield j('contentBlockStop', {'contentBlockIndex': index})
    if reason != 'guardrail_intervened':
        reason = stop_reason(calls_seen, (info.get('usage') or {}).get('completion_tokens', 0), max_tokens)
    yield j('messageStop', {'stopReason': reason})
    yield j('metadata', {'usage': _usage(info), 'metrics': {'latencyMs': int(info.get('latency_ms', 0))}})


def converse_stream(req):
    require(req.principal, 'developer', 'admin')
    request = req.json()
    value, record, is_router = resolve(req, req.params['modelId'])
    body = converse_to_chat(request, value)
    try:
        events = req.app.open_stream(req.principal, body)
    except Fault as exc:  # input refused before anything was generated: still a well-formed stream
        if not _refusal(exc):
            raise
        return Stream(converse_frames(iter([('refused', None)]), 0))
    return Stream(converse_frames(neutral(events), body.get('max_tokens', 1024)))


# ---- InvokeModel ------------------------------------------------------------------------

OPENAI_FIELDS = ('messages', 'max_tokens', 'temperature', 'top_p', 'stop', 'tools', 'tool_choice', 'response_format')
ANTHROPIC_FIELDS = ('anthropic_version', 'max_tokens', 'messages', 'system', 'temperature', 'top_p', 'stop_sequences', 'tools', 'tool_choice')


def _invoke_headers(req):
    h = req.handler.headers
    for name in ('X-Amzn-Bedrock-GuardrailIdentifier', 'X-Amzn-Bedrock-GuardrailVersion', 'X-Amzn-Bedrock-PerformanceConfig-Latency', 'X-Amzn-Bedrock-Trace'):
        if h.get(name):
            raise errors.validation(f'The {name} header is not supported by this Nuvora release')
    ctype = (h.get('Content-Type') or 'application/json').split(';')[0].strip().lower()
    if ctype != 'application/json':
        raise errors.validation('contentType must be application/json')
    accept = (h.get('Accept') or 'application/json').split(',')[0].split(';')[0].strip().lower()
    if accept not in ('application/json', '*/*'):
        raise errors.validation('accept must be application/json')


def _anthropic_blocks(role, content, where):
    if isinstance(content, str):
        return [('text', content)]
    if not isinstance(content, list) or not content:
        raise errors.validation(f'{where}.content must be a string or a non-empty list of blocks')
    items = []
    for n, block in enumerate(content):
        at = f'{where}.content[{n}]'
        kind = block.get('type') if isinstance(block, dict) else None
        if kind == 'text' and isinstance(block.get('text'), str) and set(block) <= {'type', 'text'}:
            items.append(('text', block['text']))
        elif kind == 'image':
            source = block.get('source')
            if not isinstance(source, dict) or source.get('type') != 'base64' or source.get('media_type') not in IMAGE_FORMATS.values():
                raise errors.validation(f'{at}.source must be base64 with media_type image/png, image/jpeg or image/webp')
            fmt = next(k for k, v in IMAGE_FORMATS.items() if v == source['media_type'])
            items.append(('image', _data_url(fmt, source.get('data'), at)))
        elif kind == 'tool_use' and isinstance(block.get('id'), str) and isinstance(block.get('name'), str):
            items.append(('call', block['id'], block['name'], json.dumps(block.get('input') or {}, separators=(',', ':'))))
        elif kind == 'tool_result' and isinstance(block.get('tool_use_id'), str):
            inner = block.get('content', '')
            if isinstance(inner, list):
                if any(not (isinstance(x, dict) and x.get('type') == 'text' and isinstance(x.get('text'), str)) for x in inner):
                    raise errors.validation(f'{at}.content: only text blocks are supported in a tool_result')
                inner = '\n'.join(x['text'] for x in inner)
            if not isinstance(inner, str):
                raise errors.validation(f'{at}.content must be a string or text blocks')
            inner = inner or ' '
            items.append(('result', block['tool_use_id'], ('Tool error: ' + inner) if block.get('is_error') else inner))
        else:
            raise errors.validation(f'{at}: block type "{kind}" is not supported (supported: text, image, tool_use, tool_result)')
    return items


def anthropic_to_chat(body, model_value):
    _check_keys(body, ANTHROPIC_FIELDS, 'body')
    if body.get('anthropic_version') != ANTHROPIC_VERSION:
        raise errors.validation(f'anthropic_version must be "{ANTHROPIC_VERSION}"')
    if not isinstance(body.get('max_tokens'), int) or isinstance(body.get('max_tokens'), bool):
        raise errors.validation('max_tokens is required and must be an integer')
    messages = []
    system = body.get('system')
    if system is not None:
        for item in _anthropic_blocks('user', system, 'system'):
            if item[0] != 'text':
                raise errors.validation('system may contain only text')
            messages.append({'role': 'system', 'content': item[1]})
    source = body.get('messages')
    if not isinstance(source, list) or not source:
        raise errors.validation('messages must be a non-empty list')
    for n, message in enumerate(source):
        where = f'messages[{n}]'
        _check_keys(message, ('role', 'content'), where)
        if message.get('role') not in ('user', 'assistant'):
            raise errors.validation(f'{where}.role must be user or assistant')
        messages.extend(_fold(message['role'], _anthropic_blocks(message['role'], message.get('content'), where), where))
    out = {'model': model_value, 'messages': messages, 'max_tokens': body['max_tokens']}
    for src, dst in (('temperature', 'temperature'), ('top_p', 'top_p'), ('stop_sequences', 'stop')):
        if body.get(src) is not None:
            out[dst] = body[src]
    if body.get('tools') is not None:
        if not isinstance(body['tools'], list) or not body['tools']:
            raise errors.validation('tools must be a non-empty list')
        out['tools'] = []
        for n, tool in enumerate(body['tools']):
            _check_keys(tool, ('name', 'description', 'input_schema'), f'tools[{n}]')
            function = {'name': tool.get('name'), 'parameters': tool.get('input_schema') or {'type': 'object', 'properties': {}}}
            if tool.get('description'):
                function['description'] = tool['description']
            out['tools'].append({'type': 'function', 'function': function})
    choice = body.get('tool_choice')
    if choice is not None:
        _check_keys(choice, ('type', 'name'), 'tool_choice')
        kind = choice.get('type')
        if kind in ('auto', 'none'):
            out['tool_choice'] = kind
        elif kind == 'any':
            out['tool_choice'] = 'required'
        elif kind == 'tool' and isinstance(choice.get('name'), str):
            out['tool_choice'] = {'type': 'function', 'function': {'name': choice['name']}}
        else:
            raise errors.validation('tool_choice.type must be auto, any, none or tool (with name)')
    return out


def openai_to_chat(body, model_value):
    _check_keys(body, OPENAI_FIELDS, 'body')
    if 'messages' not in body:
        raise errors.validation('body.messages is required')
    return {**body, 'model': model_value}


def _is_anthropic(body):
    return 'anthropic_version' in body


def _invoke_response(body, payload, result):
    headers = {'Content-Type': 'application/json', 'X-Amzn-Bedrock-Input-Token-Count': str((result.get('usage') or {}).get('prompt_tokens', 0)),
               'X-Amzn-Bedrock-Output-Token-Count': str((result.get('usage') or {}).get('completion_tokens', 0)),
               'X-Amzn-Bedrock-Invocation-Latency': str(int(result.get('latency_ms', 0))),
               'X-Nuvora-Evidence-Class': str(result.get('evidence_class', ''))}
    return Response(json.dumps(payload, separators=(',', ':')).encode(), headers=headers)


def _anthropic_content(result):
    content = [{'type': 'text', 'text': result['content']}] if result['content'] else []
    for block in _tool_use_blocks(result.get('tool_calls')):
        use = block['toolUse']
        content.append({'type': 'tool_use', 'id': use['toolUseId'], 'name': use['name'], 'input': use['input']})
    return content or [{'type': 'text', 'text': ''}]


def _embedding(req, record, body):
    if 'inputText' in body:
        _check_keys(body, ('inputText',), 'body')
        if not isinstance(body['inputText'], str):
            raise errors.validation('inputText must be a string')
        result = req.app.embed(req.principal, {'model': record['id'], 'input': body['inputText']})
        payload = {'embedding': result['data'][0]['embedding'], 'inputTextTokenCount': result['usage']['prompt_tokens']}
    else:
        _check_keys(body, ('input', 'encoding_format'), 'body')
        if 'input' not in body:
            raise errors.validation('body needs "input" (Nuvora/OpenAI shape) or "inputText" (Titan shape)')
        payload = req.app.embed(req.principal, {'model': record['id'], **body})
        result = payload
    tokens = result['usage']['prompt_tokens']
    return Response(json.dumps(payload, separators=(',', ':')).encode(),
                    headers={'Content-Type': 'application/json', 'X-Amzn-Bedrock-Input-Token-Count': str(tokens),
                             'X-Nuvora-Evidence-Class': str(result.get('nuvora', {}).get('evidence_class', ''))})


def invoke(req):
    require(req.principal, 'developer', 'admin')
    _invoke_headers(req)
    value, record, is_router = resolve(req, req.params['modelId'], ('chat', 'embedding'))
    body = req.json()
    if not is_router and record.get('capability') == 'embedding':
        return _embedding(req, record, body)
    if 'inputText' in body:
        raise errors.validation('inputText is an embeddings body; this model is a chat model')
    anthropic = _is_anthropic(body)
    chat = (anthropic_to_chat if anthropic else openai_to_chat)(body, value)
    result = req.app.chat(req.principal, chat)
    calls = result.get('tool_calls') or []
    reason = stop_reason(calls, result['usage'].get('completion_tokens', 0), chat.get('max_tokens', 1024))
    if anthropic:
        usage = result['usage']
        payload = {'id': 'msg_' + secrets.token_hex(12), 'type': 'message', 'role': 'assistant', 'model': result['model'], 'content': _anthropic_content(result),
                   'stop_reason': reason, 'stop_sequence': None,
                   'usage': {'input_tokens': usage.get('prompt_tokens', 0), 'output_tokens': usage.get('completion_tokens', 0)}}
    else:
        message = {'role': 'assistant', 'content': result['content'] if result['content'] or not calls else None, **({'tool_calls': calls} if calls else {})}
        payload = {'id': 'chatcmpl-' + secrets.token_hex(12), 'object': 'chat.completion', 'model': result['model'],
                   'choices': [{'index': 0, 'message': message, 'finish_reason': 'tool_calls' if calls else 'length' if reason == 'max_tokens' else 'stop'}],
                   'usage': result['usage'], 'nuvora': {'evidence_class': result.get('evidence_class'), 'cached': result.get('cached'), 'cost': result.get('cost')}}
    return _invoke_response(body, payload, result)


def _anthropic_events(events, model, max_tokens):
    yield {'type': 'message_start', 'message': {'id': 'msg_' + secrets.token_hex(12), 'type': 'message', 'role': 'assistant', 'model': model, 'content': [],
                                                'stop_reason': None, 'stop_sequence': None, 'usage': {'input_tokens': 0, 'output_tokens': 0}}}
    index, open_text, calls_seen, info = -1, False, False, {}
    for kind, value in events:
        if kind == 'text':
            if not open_text:
                index, open_text = index + 1, True
                yield {'type': 'content_block_start', 'index': index, 'content_block': {'type': 'text', 'text': ''}}
            yield {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'text_delta', 'text': value}}
        elif kind == 'calls':
            if open_text:
                yield {'type': 'content_block_stop', 'index': index}
                open_text = False
            calls_seen = True
            for block in _tool_use_blocks(value):
                index += 1
                use = block['toolUse']
                yield {'type': 'content_block_start', 'index': index, 'content_block': {'type': 'tool_use', 'id': use['toolUseId'], 'name': use['name'], 'input': {}}}
                yield {'type': 'content_block_delta', 'index': index, 'delta': {'type': 'input_json_delta', 'partial_json': json.dumps(use['input'], separators=(',', ':'))}}
                yield {'type': 'content_block_stop', 'index': index}
        elif kind == 'done':
            info = value
    if open_text:
        yield {'type': 'content_block_stop', 'index': index}
    usage = info.get('usage') or {}
    yield {'type': 'message_delta', 'delta': {'stop_reason': stop_reason(calls_seen, usage.get('completion_tokens', 0), max_tokens), 'stop_sequence': None},
           'usage': {'output_tokens': usage.get('completion_tokens', 0)}}
    yield {'type': 'message_stop', 'amazon-bedrock-invocationMetrics': {'inputTokenCount': usage.get('prompt_tokens', 0), 'outputTokenCount': usage.get('completion_tokens', 0),
                                                                          'invocationLatency': int(info.get('latency_ms', 0))}}


def _openai_events(events, model, max_tokens):
    head = {'id': 'chatcmpl-' + secrets.token_hex(12), 'object': 'chat.completion.chunk', 'model': model}
    yield {**head, 'choices': [{'index': 0, 'delta': {'role': 'assistant', 'content': ''}, 'finish_reason': None}]}
    calls_seen = False
    for kind, value in events:
        if kind == 'text':
            yield {**head, 'choices': [{'index': 0, 'delta': {'content': value}, 'finish_reason': None}]}
        elif kind == 'calls':
            calls_seen = True
            yield {**head, 'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': i, **c} for i, c in enumerate(value)]}, 'finish_reason': None}]}
        elif kind == 'done':
            reason = stop_reason(calls_seen, (value.get('usage') or {}).get('completion_tokens', 0), max_tokens)
            yield {**head, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls' if calls_seen else 'length' if reason == 'max_tokens' else 'stop'}],
                   'usage': value.get('usage', {}), 'nuvora': {'evidence_class': value.get('evidence_class'), 'cached': value.get('cached'), 'cost': value.get('cost')}}


def _refusal_stops(events):
    """Invoke* streams have no guardrail-intervened shape: a refusal is an exception frame."""
    for kind, value in events:
        if kind == 'refused':
            raise Fault('Output refused by guardrail', 422)
        yield kind, value


def invoke_stream(req):
    require(req.principal, 'developer', 'admin')
    _invoke_headers(req)
    value, record, is_router = resolve(req, req.params['modelId'], ('chat', 'embedding'))
    if not is_router and record.get('capability') == 'embedding':
        raise errors.validation('Embedding models do not stream; use InvokeModel')
    body = req.json()
    anthropic = _is_anthropic(body)
    chat = (anthropic_to_chat if anthropic else openai_to_chat)(body, value)
    events = req.app.open_stream(req.principal, chat)
    maximum = chat.get('max_tokens', 1024)
    shape = _anthropic_events if anthropic else _openai_events
    name = value

    def frames():
        for payload in shape(_refusal_stops(neutral(events)), name, maximum):
            yield es.chunk_event(json.dumps(payload, separators=(',', ':')))
    return Stream(frames())


# ---- CountTokens ------------------------------------------------------------------------

def estimate_tokens(chat):
    """Characters / 4 over message text, tool-call arguments and tool definitions. An estimate, not a tokenizer."""
    total = 0
    for m in chat['messages']:
        content = m.get('content')
        if isinstance(content, list):
            total += sum(len(p.get('text', '')) + (1000 * 4 if p.get('type') == 'image_url' else 0) for p in content)
        else:
            total += len(content or '')
        total += sum(len(c['function']['name']) + len(c['function']['arguments']) for c in m.get('tool_calls', []))
    total += len(canonical(chat.get('tools') or []))
    return total // 4 + 1


def count_tokens(req):
    require(req.principal, 'developer', 'admin')
    value, record, is_router = resolve(req, req.params['modelId'], ('chat', 'embedding'))
    request = req.json()
    _check_keys(request, ('input',), 'request')
    source = request.get('input')
    if not isinstance(source, dict) or len(source) != 1:
        raise errors.validation('input must hold exactly one of converse, invokeModel')
    (kind, spec), = source.items()
    if kind == 'converse':
        chat = converse_to_chat(spec, value)
    elif kind == 'invokeModel':
        _check_keys(spec, ('body',), 'input.invokeModel')
        try:
            body = json.loads(base64.b64decode(spec.get('body') or '', validate=True))
        except (binascii.Error, ValueError):
            raise errors.validation('input.invokeModel.body must be base64-encoded JSON')
        if not isinstance(body, dict):
            raise errors.validation('input.invokeModel.body must be a JSON object')
        if not is_router and record.get('capability') == 'embedding':
            text = body.get('inputText', body.get('input'))
            texts = [text] if isinstance(text, str) else text
            if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
                raise errors.validation('input.invokeModel.body needs inputText or input')
            return Response({'inputTokens': sum(len(t) // 4 + 1 for t in texts)}, headers={'X-Nuvora-Token-Count': 'estimate; characters/4'})
        chat = (anthropic_to_chat if _is_anthropic(body) else openai_to_chat)(body, value)
    else:
        raise errors.validation('input must hold exactly one of converse, invokeModel')
    return Response({'inputTokens': estimate_tokens(chat)}, headers={'X-Nuvora-Token-Count': 'estimate; characters/4'})


# ---- GetFoundationModel -----------------------------------------------------------------

def get_foundation_model(req):
    from .foundation import summary
    ident = req.params['modelIdentifier']
    kind, ident = _arn_tail(ident)
    if kind not in (None, 'foundation-model'):
        raise errors.not_found(f'Could not resolve the foundation model {req.params["modelIdentifier"]}')
    try:
        model = req.app.get(req.principal, 'models', ident)
    except KeyError:
        raise errors.not_found(f'Could not resolve the foundation model {req.params["modelIdentifier"]}')
    if not model.get('enabled'):
        raise errors.not_found(f'Could not resolve the foundation model {req.params["modelIdentifier"]}')
    return Response({'modelDetails': summary(model, req.region or 'local')})


HANDLERS = {'Converse': converse, 'ConverseStream': converse_stream, 'InvokeModel': invoke, 'InvokeModelWithResponseStream': invoke_stream,
            'CountTokens': count_tokens, 'GetFoundationModel': get_foundation_model}
