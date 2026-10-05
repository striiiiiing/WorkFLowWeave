"""模型发现响应边界：注入 HTTP 传输验证非 JSON 诊断、脱敏及不重试。"""

import httpx
import pytest

from logagent.ai import AIService, OpenAIChannelFactory
from logagent.errors import LogAgentError
from logagent.models import AIConfig


@pytest.mark.parametrize("body", ["", "<html>API gateway homepage</html>", "{invalid"])
async def test_non_json_model_catalog_keeps_diagnostic_without_retry(body):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text=body)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        service = AIService(channel_factories={"http": OpenAIChannelFactory(client)})
        try:
            with pytest.raises(LogAgentError) as caught:
                await service.list_models(AIConfig(
                    id="provider", provider="http", base_url="http://provider.test/v1", retries=3,
                ))
            error = caught.value.info
            assert error.code == "invalid_response"
            assert "API 路径" in error.message
            assert error.details["response_body"] == body
            assert error.details["status_code"] == 200
            assert error.details["retryable"] is False
            assert len(requests) == 1
            assert requests[0].url.path == "/v1/models"
        finally:
            await service.close()
