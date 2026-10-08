# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""`application/vnd.amazon.eventstream` framing: encode and decode.

Frame layout (big endian):
  total length (4) | headers length (4) | CRC32 of those 8 bytes (4)
  headers | payload | CRC32 of everything before it (4)
Header: name length (1) | name | value type (1) | value (type dependent)."""
import base64
import json
import struct
import uuid
import zlib

CONTENT_TYPE = 'application/vnd.amazon.eventstream'
MAX_FRAME = 24 * 1024 * 1024
(T_TRUE, T_FALSE, T_BYTE, T_SHORT, T_INT, T_LONG, T_BYTES, T_STRING, T_TIMESTAMP, T_UUID) = range(10)
_FIXED = {T_BYTE: '>b', T_SHORT: '>h', T_INT: '>i', T_LONG: '>q', T_TIMESTAMP: '>q'}


class EventStreamError(ValueError):
    pass


def _crc(data, seed=0):
    return zlib.crc32(data, seed) & 0xFFFFFFFF


def encode_header(name, value):
    raw = name.encode()
    if not 1 <= len(raw) <= 255:
        raise EventStreamError('header names are 1-255 bytes')
    out = bytes([len(raw)]) + raw
    if value is True:
        return out + bytes([T_TRUE])
    if value is False:
        return out + bytes([T_FALSE])
    if isinstance(value, int):
        return out + (bytes([T_INT]) + struct.pack('>i', value) if -2**31 <= value < 2**31 else bytes([T_LONG]) + struct.pack('>q', value))
    if isinstance(value, str):
        data = value.encode()
        if len(data) > 0xFFFF:
            raise EventStreamError('header value too long')
        return out + bytes([T_STRING]) + struct.pack('>H', len(data)) + data
    if isinstance(value, (bytes, bytearray)):
        if len(value) > 0xFFFF:
            raise EventStreamError('header value too long')
        return out + bytes([T_BYTES]) + struct.pack('>H', len(value)) + bytes(value)
    if isinstance(value, uuid.UUID):
        return out + bytes([T_UUID]) + value.bytes
    raise EventStreamError('unsupported header value type')


def encode(headers, payload=b''):
    """One frame. `headers` is a dict (insertion order kept) or list of pairs; str values are
    string headers, bytes values are byte-array headers."""
    pairs = headers.items() if isinstance(headers, dict) else headers
    block = b''.join(encode_header(k, v) for k, v in pairs)
    payload = payload.encode() if isinstance(payload, str) else bytes(payload)
    total = 12 + len(block) + len(payload) + 4
    if total > MAX_FRAME:
        raise EventStreamError('frame too large')
    prelude = struct.pack('>II', total, len(block))
    head = prelude + struct.pack('>I', _crc(prelude)) + block + payload
    return head + struct.pack('>I', _crc(head))


def decode_one(buf, offset=0):
    """Decode the frame starting at `offset`. Returns (headers, payload, next_offset), or None
    when the buffer holds less than one whole frame. Raises EventStreamError on corruption."""
    if len(buf) - offset < 12:
        return None
    total, hlen = struct.unpack_from('>II', buf, offset)
    (prelude_crc,) = struct.unpack_from('>I', buf, offset + 8)
    if _crc(bytes(buf[offset:offset + 8])) != prelude_crc:
        raise EventStreamError('prelude CRC mismatch')
    if total < 16 or total > MAX_FRAME or hlen > total - 16:
        raise EventStreamError('invalid frame lengths')
    if len(buf) - offset < total:
        return None
    end = offset + total
    (message_crc,) = struct.unpack_from('>I', buf, end - 4)
    if _crc(bytes(buf[offset:end - 4])) != message_crc:
        raise EventStreamError('message CRC mismatch')
    headers = _decode_headers(bytes(buf[offset + 12:offset + 12 + hlen]))
    return headers, bytes(buf[offset + 12 + hlen:end - 4]), end


def _decode_headers(block):
    headers, i = {}, 0
    try:
        while i < len(block):
            n = block[i]
            raw_name = block[i + 1:i + 1 + n]
            if len(raw_name) != n:
                raise EventStreamError('truncated header')
            name = raw_name.decode()
            i += 1 + n
            kind = block[i]
            i += 1
            if kind == T_TRUE:
                value = True
            elif kind == T_FALSE:
                value = False
            elif kind in _FIXED:
                size = struct.calcsize(_FIXED[kind])
                (value,) = struct.unpack_from(_FIXED[kind], block, i)
                i += size
            elif kind in (T_BYTES, T_STRING):
                (size,) = struct.unpack_from('>H', block, i)
                raw = block[i + 2:i + 2 + size]
                if len(raw) != size:
                    raise EventStreamError('truncated header value')
                value = raw.decode() if kind == T_STRING else raw
                i += 2 + size
            elif kind == T_UUID:
                raw = block[i:i + 16]
                if len(raw) != 16:
                    raise EventStreamError('truncated header value')
                value = uuid.UUID(bytes=raw)
                i += 16
            else:
                raise EventStreamError('unknown header type %d' % kind)
            headers[name] = value
    except (IndexError, struct.error, UnicodeDecodeError) as exc:
        raise EventStreamError('malformed headers') from exc
    return headers


def decode(data):
    """Decode every frame in `data`; trailing partial bytes are an error."""
    out, offset = [], 0
    while offset < len(data):
        item = decode_one(data, offset)
        if item is None:
            raise EventStreamError('truncated frame')
        headers, payload, offset = item
        out.append((headers, payload))
    return out


class Decoder:
    """Incremental decoder: feed(bytes) returns the frames completed so far."""

    def __init__(self):
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        out, offset = [], 0
        while True:
            item = decode_one(self.buffer, offset)
            if item is None:
                break
            headers, payload, offset = item
            out.append((headers, payload))
        del self.buffer[:offset]
        return out


# Bedrock event helpers -------------------------------------------------------------------

def event(event_type, payload=b'', content_type='application/json'):
    headers = {':event-type': event_type, ':content-type': content_type, ':message-type': 'event'}
    return encode(headers, payload)


def json_event(event_type, obj):
    """A typed JSON event such as ConverseStream's `contentBlockDelta`."""
    return event(event_type, json.dumps(obj, separators=(',', ':')))


def chunk_event(data):
    """InvokeModelWithResponseStream chunk: `{"bytes": base64(data)}` under event type `chunk`."""
    data = data.encode() if isinstance(data, str) else bytes(data)
    return json_event('chunk', {'bytes': base64.b64encode(data).decode()})


def exception_event(exception_type, message):
    headers = {':exception-type': exception_type, ':content-type': 'application/json', ':message-type': 'exception'}
    return encode(headers, json.dumps({'message': message}, separators=(',', ':')))
