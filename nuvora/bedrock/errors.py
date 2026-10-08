# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Bedrock error shape: JSON `{"message": ...}` plus an `x-amzn-ErrorType` header."""
import json
import secrets

# error type -> HTTP status, as published in the Bedrock API references.
STATUS = {
    'ValidationException': 400,
    'AccessDeniedException': 403,
    'ResourceNotFoundException': 404,
    'ConflictException': 409,
    'ThrottlingException': 429,
    'ServiceQuotaExceededException': 400,
    'ModelTimeoutException': 408,
    'ModelNotReadyException': 429,
    'ModelErrorException': 424,
    'ModelStreamErrorException': 424,
    'InternalServerException': 500,
    'ServiceUnavailableException': 503,
    # Gateway-level errors raised before an operation is reached.
    'UnrecognizedClientException': 403,
    'InvalidSignatureException': 403,
    'IncompleteSignatureException': 403,
    'MissingAuthenticationTokenException': 403,
    'ExpiredTokenException': 403,
    'UnknownOperationException': 404,
    'UnsupportedOperationException': 501,
}


class BedrockError(Exception):
    def __init__(self, error_type, message, status=None):
        super().__init__(message)
        self.error_type = error_type
        self.message = message
        self.status = status or STATUS.get(error_type, 500)

    def body(self):
        return json.dumps({'message': self.message}, separators=(',', ':')).encode()

    def headers(self, request_id=None):
        return {'Content-Type': 'application/json', 'x-amzn-ErrorType': self.error_type,
                'x-amzn-RequestId': request_id or new_request_id()}


def new_request_id():
    h = secrets.token_hex(16)
    return f'{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}'


def validation(message):
    return BedrockError('ValidationException', message)


def access_denied(message):
    return BedrockError('AccessDeniedException', message)


def not_found(message):
    return BedrockError('ResourceNotFoundException', message)


def throttled(message):
    return BedrockError('ThrottlingException', message)


def internal(message='Internal server error'):
    return BedrockError('InternalServerException', message)


def unavailable(message):
    return BedrockError('ServiceUnavailableException', message)


def from_fault(exc):
    """Map a Nuvora Fault (message, status) onto the closest Bedrock error type."""
    status = getattr(exc, 'status', 400)
    kind = {400: 'ValidationException', 401: 'UnrecognizedClientException', 403: 'AccessDeniedException',
            404: 'ResourceNotFoundException', 409: 'ConflictException', 413: 'ValidationException',
            415: 'ValidationException', 422: 'ValidationException', 429: 'ThrottlingException',
            502: 'ModelErrorException', 503: 'ServiceUnavailableException', 504: 'ModelTimeoutException'}.get(status)
    if kind is None:
        kind = 'InternalServerException' if status >= 500 else 'ValidationException'
    return BedrockError(kind, str(exc))


# Exceptions the bedrock-runtime event streams model; anything else is folded into the nearest one.
STREAM_EXCEPTIONS = {'InternalServerException', 'ModelStreamErrorException', 'ValidationException', 'ThrottlingException', 'ServiceUnavailableException'}
STREAM_FOLD = {'ModelErrorException': 'ModelStreamErrorException', 'ModelTimeoutException': 'ModelStreamErrorException',
               'AccessDeniedException': 'ValidationException', 'ResourceNotFoundException': 'ValidationException', 'ConflictException': 'ValidationException'}


def stream_exception(error_type):
    """The `:exception-type` header value for a failure after a stream started (lowerCamelCase, as SDKs expect)."""
    kind = STREAM_FOLD.get(error_type, error_type)
    if kind not in STREAM_EXCEPTIONS:
        kind = 'InternalServerException'
    return kind[0].lower() + kind[1:]
