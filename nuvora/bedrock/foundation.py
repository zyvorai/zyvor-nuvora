# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""ListFoundationModels from the tenant's model registry (the B1 proof operation)."""
from . import errors
from .router import Response

QUERY = {'byProvider', 'byCustomizationType', 'byOutputModality', 'byInferenceType'}
OUTPUT = {'chat': ('TEXT', ['TEXT']), 'embedding': ('EMBEDDING', ['TEXT']), 'image': ('IMAGE', ['TEXT']), 'transcription': ('TEXT', ['SPEECH'])}


def summary(model, region):
    capability = model.get('capability', 'chat')
    output, inputs = OUTPUT.get(capability, ('TEXT', ['TEXT']))
    inputs = list(inputs) + (['IMAGE'] if model.get('vision') else [])
    return {'modelArn': f"arn:nuvora:bedrock:{region}::foundation-model/{model['id']}", 'modelId': model['id'],
            'modelName': model.get('name') or model['id'], 'providerName': model.get('provider', ''),
            'inputModalities': inputs, 'outputModalities': [output],
            'responseStreamingSupported': capability == 'chat',
            'customizationsSupported': [], 'inferenceTypesSupported': ['ON_DEMAND'],
            'modelLifecycle': {'status': 'ACTIVE'}}


def list_foundation_models(req):
    unknown = sorted(set(req.query) - QUERY)
    if unknown:
        raise errors.validation('Unsupported query parameter: ' + ', '.join(unknown))
    out = [summary(m, req.region or 'local') for m in req.app.list(req.principal, 'models') if m.get('enabled')]
    wanted = req.query.get
    if wanted('byProvider'):
        out = [m for m in out if m['providerName'].lower() == wanted('byProvider').lower()]
    if wanted('byOutputModality'):
        if wanted('byOutputModality') not in ('TEXT', 'IMAGE', 'EMBEDDING'):
            raise errors.validation('byOutputModality must be TEXT, IMAGE or EMBEDDING')
        out = [m for m in out if wanted('byOutputModality') in m['outputModalities']]
    if wanted('byInferenceType'):
        if wanted('byInferenceType') not in ('ON_DEMAND', 'PROVISIONED'):
            raise errors.validation('byInferenceType must be ON_DEMAND or PROVISIONED')
        out = [m for m in out if wanted('byInferenceType') in m['inferenceTypesSupported']]
    if wanted('byCustomizationType'):
        if wanted('byCustomizationType') not in ('FINE_TUNING', 'CONTINUED_PRE_TRAINING', 'DISTILLATION'):
            raise errors.validation('byCustomizationType must be FINE_TUNING, CONTINUED_PRE_TRAINING or DISTILLATION')
        out = []  # no registry model advertises Bedrock-style customization
    return Response({'modelSummaries': out})
