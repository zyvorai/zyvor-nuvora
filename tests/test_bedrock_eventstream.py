# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
import base64
import json
import unittest
import uuid

from nuvora.bedrock import eventstream as es

try:
    from botocore.eventstream import EventStreamBuffer
except ImportError:  # optional: pip install boto3
    EventStreamBuffer = None


class Frames(unittest.TestCase):
    def test_known_empty_frame(self):
        # The minimal frame (no headers, no payload): 16 bytes, CRCs fixed by the format.
        self.assertEqual(es.encode({}, b'').hex(), '000000100000000005c248eb7d98c8ff')
        self.assertEqual(es.decode(bytes.fromhex('000000100000000005c248eb7d98c8ff')), [({}, b'')])

    def test_round_trip_all_header_types(self):
        headers = {'s': 'text', 'b': b'\x00\xff', 't': True, 'f': False, 'i': 7, 'big': 2**40, 'u': uuid.UUID(int=5)}
        frame = es.encode(headers, b'payload')
        (got, payload), = es.decode(frame)
        self.assertEqual(payload, b'payload')
        self.assertEqual(got, headers)
        self.assertEqual(frame[0:4], len(frame).to_bytes(4, 'big'))

    def test_corruption_is_detected(self):
        frame = bytearray(es.encode({'a': 'b'}, b'hello'))
        for index in (2, 9, 14, len(frame) - 6, len(frame) - 1):
            broken = bytearray(frame)
            broken[index] ^= 0x01
            with self.subTest(index), self.assertRaises(es.EventStreamError):
                es.decode(bytes(broken))
        with self.assertRaises(es.EventStreamError):
            es.decode(bytes(frame[:-3]))

    def test_incremental_decoder_handles_split_and_batched_input(self):
        data = b''.join(es.json_event('contentBlockDelta', {'n': i}) for i in range(5))
        decoder, seen = es.Decoder(), []
        for i in range(0, len(data), 7):
            seen += decoder.feed(data[i:i + 7])
        self.assertEqual([json.loads(p)['n'] for _, p in seen], list(range(5)))
        self.assertEqual(len(decoder.buffer), 0)

    def test_bedrock_helpers(self):
        (h, p), = es.decode(es.chunk_event(b'{"x":1}'))
        self.assertEqual((h[':event-type'], h[':message-type'], h[':content-type']), ('chunk', 'event', 'application/json'))
        self.assertEqual(base64.b64decode(json.loads(p)['bytes']), b'{"x":1}')
        (h, p), = es.decode(es.exception_event('ThrottlingException', 'slow down'))
        self.assertEqual((h[':message-type'], h[':exception-type'], json.loads(p)), ('exception', 'ThrottlingException', {'message': 'slow down'}))


@unittest.skipIf(EventStreamBuffer is None, 'botocore not installed')
class BotocoreAgrees(unittest.TestCase):
    def test_botocore_decodes_our_frames_and_we_decode_a_botocore_style_stream(self):
        data = es.json_event('messageStart', {'role': 'assistant'}) + es.chunk_event(b'hi') + es.exception_event('ThrottlingException', 'no')
        buffer = EventStreamBuffer()
        buffer.add_data(data[:11])
        buffer.add_data(data[11:])
        events = list(buffer)
        self.assertEqual(len(events), 3)
        self.assertEqual(events[0].headers[':event-type'], 'messageStart')
        self.assertEqual(json.loads(events[0].payload), {'role': 'assistant'})
        self.assertEqual(events[2].headers[':exception-type'], 'ThrottlingException')
        # CRC validation by botocore rejects what we reject
        broken = bytearray(data)
        broken[-1] ^= 1
        with self.assertRaises(Exception):
            buffer = EventStreamBuffer()
            buffer.add_data(bytes(broken))
            list(buffer)


if __name__ == '__main__':
    unittest.main()
