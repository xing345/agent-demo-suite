"""回归测试：模型网关的 response_format 逐级降级。

背景
----
``OpenAICompatibleGateway`` 原先无条件把 ``response_format`` 固定成
``{"type": "json_schema", "strict": true}``。DeepSeek 对 json_schema 直接返回：

    HTTP 400 {"error": {"message": "This response_format type is unavailable now",
                        "type": "invalid_request_error"}}

结果整个 run 创建失败（``ModelRouterError: all model providers failed``），
而且这个错误还被判定为"可重试"，于是重试一次、慢一次、还是失败。

修好的逻辑是 json_schema → json_object → 不约束，逐级降级，且降级不计入重试。
这些用例守住这个行为，特别是"不能把参数不被接受当成网络抖动来重试"。
"""
from __future__ import annotations

import json

import pytest

from packages.model_gateway.openai_compatible import (
    ModelGatewayError,
    OpenAICompatibleGateway,
    _extract_json_object,
    _response_format_rejected,
)
from packages.model_gateway.router import ModelRouter


class _Schema:
    """Stand-in for a pydantic model in these tests."""

    @staticmethod
    def model_json_schema() -> dict:
        return {"type": "object", "properties": {"goal": {"type": "string"}}}

    @staticmethod
    def model_validate(data: dict) -> dict:
        if not isinstance(data, dict):
            raise ValueError("expected object")
        return data


_SCHEMA_ERROR = (
    'model provider HTTP 400: {"error":{"message":'
    '"This response_format type is unavailable now","type":"invalid_request_error"}}'
)


def _ok_response(content: str) -> dict:
    return {
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        "model": "deepseek-chat",
    }


def _rejecting_post_json(reject_types: set[str]):
    """构造一个 post_json：遇到这些 response_format type 就抛 400。"""
    calls: list[str] = []

    def _post(url, headers, payload, timeout):
        fmt = (payload.get("response_format") or {}).get("type")
        calls.append(fmt or "none")
        if fmt in reject_types:
            raise ModelGatewayError(_SCHEMA_ERROR)
        return _ok_response(json.dumps({"goal": "来自模型"}))

    _post.calls = calls  # type: ignore[attr-defined]
    return _post


def _gateway(post_json, **kwargs) -> OpenAICompatibleGateway:
    return OpenAICompatibleGateway(
        base_url="http://example.invalid",
        api_key="k",
        model="deepseek-chat",
        post_json=post_json,
        **kwargs,
    )


class TestResponseFormatRejectionDetection:
    def test_recognises_unavailable_message(self):
        assert _response_format_rejected(ModelGatewayError(_SCHEMA_ERROR))

    @pytest.mark.parametrize(
        "message",
        [
            "model provider HTTP 400: response_format json_schema not supported",
            "model provider HTTP 400: This response_format type is unavailable now",
        ],
    )
    def test_recognises_common_wording(self, message):
        assert _response_format_rejected(ModelGatewayError(message))

    def test_ignores_unrelated_errors(self):
        assert not _response_format_rejected(ModelGatewayError("network error"))
        assert not _response_format_rejected(ValueError("nope"))

    def test_ignores_generic_400_without_format_wording(self):
        """别的 400（比如参数缺失）不能被误判成"该降级"。"""
        assert not _response_format_rejected(
            ModelGatewayError('model provider HTTP 400: {"error":{"message":"missing model"}}')
        )


class TestJsonExtraction:
    def test_plain_json(self):
        assert _extract_json_object('{"a": 1}') == {"a": 1}

    def test_markdown_fence(self):
        text = '```json\n{"a": 1}\n```'
        assert _extract_json_object(text) == {"a": 1}

    def test_fence_without_language(self):
        assert _extract_json_object('```\n{"a": 1}\n```') == {"a": 1}

    def test_prose_around_object(self):
        text = '好的，计划如下：\n{"a": 1}\n希望有帮助。'
        assert _extract_json_object(text) == {"a": 1}

    def test_raises_when_no_object(self):
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object("这里完全没有 JSON")


class TestDowngradeChain:
    def test_falls_back_to_json_object_when_schema_rejected(self):
        post = _rejecting_post_json({"json_schema"})
        result = _gateway(post).complete(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert post.calls == ["json_schema", "json_object"]
        assert result.structured == {"goal": "来自模型"}

    def test_falls_back_to_unconstrained_when_both_rejected(self):
        post = _rejecting_post_json({"json_schema", "json_object"})
        result = _gateway(post).complete(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert post.calls == ["json_schema", "json_object", "none"]
        assert result.structured == {"goal": "来自模型"}

    def test_no_downgrade_when_schema_is_supported(self):
        post = _rejecting_post_json(set())
        result = _gateway(post).complete(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert post.calls == ["json_schema"]
        assert result.structured == {"goal": "来自模型"}

    def test_other_errors_are_not_downgraded(self):
        """网络错误必须原样抛出，交给 router 决定要不要重试。"""

        def _post(url, headers, payload, timeout):
            raise ModelGatewayError("model provider network error: timed out")

        with pytest.raises(ModelGatewayError, match="network error"):
            _gateway(_post).complete(
                [{"role": "user", "content": "hi"}], response_model=_Schema
            )

    def test_response_model_none_sends_no_response_format(self):
        post = _rejecting_post_json({"json_schema", "json_object"})
        result = _gateway(post).complete([{"role": "user", "content": "hi"}])
        assert post.calls == ["none"]
        assert result.structured is None

    def test_structured_output_from_fenced_content(self):
        """降级到 none 后模型常把 JSON 包在围栏里，也要能解析出来。"""
        def _post(url, headers, payload, timeout):
            return _ok_response('```json\n{"goal": "围栏里的计划"}\n```')

        result = _gateway(_post).complete(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert result.structured == {"goal": "围栏里的计划"}

    def test_generate_sync_returns_structured(self):
        post = _rejecting_post_json({"json_schema"})
        out = _gateway(post).generate_sync(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert out == {"goal": "来自模型"}


class TestRouterDoesNotRetrySchemaRejection:
    def test_router_surfaces_downgrade_without_retrying(self):
        """网关内部已经降级成功，router 只应看到一次成功调用。

        修复前：router 把 400 当成可重试错误，重试一次仍然 400，
        最后抛 ModelRouterError，用户拿到 500。
        """
        post = _rejecting_post_json({"json_schema"})
        router = ModelRouter([_gateway(post)], retries=2)
        result = router.complete(
            [{"role": "user", "content": "hi"}], response_model=_Schema
        )
        assert result.structured == {"goal": "来自模型"}
        assert [a.outcome for a in router.attempts] == ["ok"]
        # 网关内部试了两档，但 router 层面只算一次尝试
        assert post.calls == ["json_schema", "json_object"]