"""Read-only HTTP response instrumentation for the frozen single-attempt campaign."""
import json

import phase3_benchmark_v2 as campaign
from stock_research.errors import IntegrityError
from stock_research.model_adapters.chat import ChatHTTPTransport


class CaptureHTTP:
    def __init__(self):
        self.transport = ChatHTTPTransport()
        self.identities = {}
        for item in campaign.read(campaign.OUT / 'model-dispatch-plan.json')['cases']:
            self.identities.setdefault(item['message_sha256'], []).append(item['case_id'])
        self.attempted = set()

    def __call__(self, config, payload, timeout):
        identity = self.identities[campaign.digest(payload['messages'])].pop(0)
        if identity in self.attempted:
            raise IntegrityError('raw response capture forbids redispatch')
        self.attempted.add(identity)
        path = campaign.OUT / 'live' / ('raw-response-' + identity + '.json')
        try:
            response = self.transport(config, payload, timeout)
        except Exception as error:
            campaign.write_new(path, {'outcome': 'exception_no_answer', 'error_type': type(error).__name__,
                'case_id': identity, 'attempt': 1, 'usage': 'unknown', 'automatic_retry': False})
            raise
        safe = response
        encoded = json.dumps(response, ensure_ascii=False)
        if config.api_key in encoded:
            safe = {'withheld': 'credential_reflection', 'case_id': identity}
        elif len(encoded.encode('utf8')) > 1024 * 1024:
            safe = {'withheld': 'bounded_response_size', 'case_id': identity}
        campaign.write_new(path, {'case_id': identity, 'attempt': 1, 'raw_response': safe})
        return response


if __name__ == '__main__':
    campaign.ChatHTTPTransport = CaptureHTTP
    campaign.live()
