# SPDX-License-Identifier: LicenseRef-Zyvor-Production-1.0
"""Path and method dispatch for the Bedrock REST surface.

Every operation Nuvora recognises is listed here under the Bedrock service that owns it
(requests are routed by method and path alone: SDKs sign several of these services with the
signing name `bedrock`, so the credential scope cannot choose the route). A listed operation with no handler answers 501 UnsupportedOperationException
naming the operation; an unlisted request answers 404 UnknownOperationException. Nothing is
silently ignored."""
from urllib.parse import unquote

from . import errors


class Response:
    def __init__(self, body=None, status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}


class Stream:
    """A body of ready-made event-stream frames (bytes), written as they are produced."""

    def __init__(self, frames, status=200, headers=None):
        self.frames, self.status, self.headers = frames, status, headers or {}


class Request:
    def __init__(self, handler, method, path, params, query, body, principal, service, region, request_id, route):
        self.handler, self.method, self.path, self.params, self.query = handler, method, path, params, query
        self.body, self.principal, self.service, self.region = body, principal, service, region
        self.request_id, self.route = request_id, route

    @property
    def app(self):
        return self.handler.server.platform

    def json(self):
        import json
        if not self.body:
            return {}
        try:
            data = json.loads(self.body)
        except (ValueError, UnicodeDecodeError) as exc:
            raise errors.validation('Request body is not valid JSON') from exc
        if not isinstance(data, dict):
            raise errors.validation('Request body must be a JSON object')
        return data


class Route:
    def __init__(self, service, method, template, operation, handler=None):
        self.service, self.method, self.template, self.operation, self.handler = service, method, template, operation, handler
        self.segments = [s for s in template.split('/') if s]

    def match(self, segments):
        if len(segments) != len(self.segments):
            return None
        params = {}
        for want, got in zip(self.segments, segments):
            if want.startswith('{') and want.endswith('}'):
                params[want[1:-1]] = got
            elif want != got:
                return None
        return params


class Router:
    def __init__(self):
        self.routes = []

    def register(self, service, method, template, operation, handler=None):
        self.routes.append(Route(service, method, template, operation, handler))

    def unregister(self, operation):
        self.routes = [r for r in self.routes if r.operation != operation]

    def find(self, service, method, raw_path):
        """(route, params). `service` None (bearer auth) searches every service."""
        segments = [unquote(s) for s in raw_path.split('/') if s]
        for route in self.routes:
            if route.method != method or (service is not None and route.service != service):
                continue
            params = route.match(segments)
            if params is not None:
                return route, params
        raise errors.BedrockError('UnknownOperationException', f'Unknown operation: {method} {raw_path.split("?")[0]}')


# (service, method, path template, operation). Handlers attach separately so later packages
# add behaviour without touching the table.
RUNTIME, CONTROL, AGENT, AGENT_RUNTIME = 'bedrock-runtime', 'bedrock', 'bedrock-agent', 'bedrock-agent-runtime'
OPERATIONS = [
    (RUNTIME, 'POST', '/model/{modelId}/converse', 'Converse'),
    (RUNTIME, 'POST', '/model/{modelId}/converse-stream', 'ConverseStream'),
    (RUNTIME, 'POST', '/model/{modelId}/invoke', 'InvokeModel'),
    (RUNTIME, 'POST', '/model/{modelId}/invoke-with-response-stream', 'InvokeModelWithResponseStream'),
    (RUNTIME, 'POST', '/model/{modelId}/count-tokens', 'CountTokens'),
    (RUNTIME, 'POST', '/guardrail/{guardrailIdentifier}/version/{guardrailVersion}/apply', 'ApplyGuardrail'),
    (RUNTIME, 'POST', '/async-invoke', 'StartAsyncInvoke'),
    (RUNTIME, 'GET', '/async-invoke', 'ListAsyncInvokes'),
    (RUNTIME, 'GET', '/async-invoke/{invocationArn}', 'GetAsyncInvoke'),
    (CONTROL, 'GET', '/foundation-models', 'ListFoundationModels'),
    (CONTROL, 'GET', '/foundation-models/{modelIdentifier}', 'GetFoundationModel'),
    (CONTROL, 'GET', '/inference-profiles', 'ListInferenceProfiles'),
    (CONTROL, 'GET', '/inference-profiles/{inferenceProfileIdentifier}', 'GetInferenceProfile'),
    (CONTROL, 'POST', '/guardrails', 'CreateGuardrail'),
    (CONTROL, 'GET', '/guardrails', 'ListGuardrails'),
    (CONTROL, 'GET', '/guardrails/{guardrailIdentifier}', 'GetGuardrail'),
    (CONTROL, 'PUT', '/guardrails/{guardrailIdentifier}', 'UpdateGuardrail'),
    (CONTROL, 'DELETE', '/guardrails/{guardrailIdentifier}', 'DeleteGuardrail'),
    (CONTROL, 'POST', '/guardrails/{guardrailIdentifier}', 'CreateGuardrailVersion'),
    (CONTROL, 'PUT', '/logging/modelinvocations', 'PutModelInvocationLoggingConfiguration'),
    (CONTROL, 'GET', '/logging/modelinvocations', 'GetModelInvocationLoggingConfiguration'),
    (CONTROL, 'DELETE', '/logging/modelinvocations', 'DeleteModelInvocationLoggingConfiguration'),
    (CONTROL, 'POST', '/model-customization-jobs', 'CreateModelCustomizationJob'),
    (CONTROL, 'GET', '/model-customization-jobs', 'ListModelCustomizationJobs'),
    (CONTROL, 'GET', '/model-customization-jobs/{jobIdentifier}', 'GetModelCustomizationJob'),
    (CONTROL, 'POST', '/evaluation-jobs', 'CreateEvaluationJob'),
    (CONTROL, 'GET', '/evaluation-jobs', 'ListEvaluationJobs'),
    (CONTROL, 'GET', '/evaluation-jobs/{jobIdentifier}', 'GetEvaluationJob'),
    (CONTROL, 'POST', '/listTagsForResource', 'ListTagsForResource'),
    (CONTROL, 'POST', '/tagResource', 'TagResource'),
    (CONTROL, 'POST', '/untagResource', 'UntagResource'),
    (AGENT, 'PUT', '/agents', 'CreateAgent'),
    (AGENT, 'POST', '/agents', 'ListAgents'),
    (AGENT, 'GET', '/agents/{agentId}', 'GetAgent'),
    (AGENT, 'PUT', '/agents/{agentId}', 'UpdateAgent'),
    (AGENT, 'DELETE', '/agents/{agentId}', 'DeleteAgent'),
    (AGENT, 'PUT', '/agents/{agentId}/agentaliases', 'CreateAgentAlias'),
    (AGENT, 'POST', '/agents/{agentId}/agentaliases', 'ListAgentAliases'),
    (AGENT, 'POST', '/agents/{agentId}/agentversions', 'ListAgentVersions'),
    (AGENT, 'PUT', '/knowledgebases', 'CreateKnowledgeBase'),
    (AGENT, 'POST', '/knowledgebases', 'ListKnowledgeBases'),
    (AGENT, 'GET', '/knowledgebases/{knowledgeBaseId}', 'GetKnowledgeBase'),
    (AGENT, 'DELETE', '/knowledgebases/{knowledgeBaseId}', 'DeleteKnowledgeBase'),
    (AGENT, 'PUT', '/knowledgebases/{knowledgeBaseId}/datasources', 'CreateDataSource'),
    (AGENT, 'PUT', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}/ingestionjobs', 'StartIngestionJob'),
    (AGENT, 'POST', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}/ingestionjobs', 'ListIngestionJobs'),
    (AGENT, 'GET', '/knowledgebases/{knowledgeBaseId}/datasources/{dataSourceId}/ingestionjobs/{ingestionJobId}', 'GetIngestionJob'),
    (AGENT_RUNTIME, 'POST', '/agents/{agentId}/agentAliases/{agentAliasId}/sessions/{sessionId}/text', 'InvokeAgent'),
    (AGENT_RUNTIME, 'POST', '/knowledgebases/{knowledgeBaseId}/retrieve', 'Retrieve'),
    (AGENT_RUNTIME, 'POST', '/retrieveAndGenerate', 'RetrieveAndGenerate'),
    (AGENT_RUNTIME, 'POST', '/flows/{flowIdentifier}/aliases/{flowAliasIdentifier}', 'InvokeFlow'),
]


def default_router():
    router = Router()
    for service, method, template, operation in OPERATIONS:
        router.register(service, method, template, operation)
    return router
