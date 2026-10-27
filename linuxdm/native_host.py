"""Chrome native messaging protocol (stdout is reserved for framed JSON)."""
import json
import os
import struct
import sys
from .bridge import submit, submit_capture, settle_capture

MAX_MESSAGE = 65536


def read_exact(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            raise ValueError('Incomplete native message.')
        chunks.extend(chunk)
    return bytes(chunks)


def read_message(stream):
    header = stream.read(4)
    if not header:
        return None
    if len(header) < 4:
        header += read_exact(stream, 4 - len(header))
    length = struct.unpack('=I', header)[0]
    if not 0 < length <= MAX_MESSAGE:
        raise ValueError('Invalid native message size.')
    return json.loads(read_exact(stream, length))


def write_message(stream, value):
    data = json.dumps(value).encode('utf-8')
    stream.write(struct.pack('=I', len(data)) + data)
    stream.flush()


def handle_message(message):
    if not isinstance(message, dict):
        raise ValueError('Invalid request.')
    if message.get('action') == 'ping':
        return {'ok': True, 'autoCapture': True, 'message': 'LinuxDM bridge is connected.'}
    if message.get('action') == 'download':
        return submit(message.get('url'))
    if message.get('action') == 'video':
        return submit(message.get('url'), kind='video', title=message.get('title', ''))
    if message.get('action') == 'capture':
        return submit_capture(message.get('url'), message.get('requestId'),
                              filename=message.get('filename', ''), mime=message.get('mime', ''))
    if message.get('action') == 'capture_status':
        return settle_capture(message.get('requestId'))
    raise ValueError('Unsupported request.')


def main():
    if os.name == 'nt':
        import msvcrt
        msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
        msvcrt.setmode(sys.stdout.fileno(), os.O_BINARY)
    message = None
    try:
        message = read_message(sys.stdin.buffer)
        if message is None:
            return
        result = handle_message(message)
    except Exception as exc:
        result = {'ok': False, 'message': str(exc)}
        if isinstance(message, dict) and message.get('action') in ('capture', 'capture_status'):
            # A failed receipt must never be mistaken for a definite rejection.
            result['connectionError'] = True
    write_message(sys.stdout.buffer, result)


if __name__ == '__main__':
    main()
