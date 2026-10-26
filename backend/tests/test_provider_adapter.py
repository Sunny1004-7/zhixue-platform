from dataclasses import replace
import json
import httpx
import pytest

from app.domains.model_gateway.adapters.openai_compatible import OpenAICompatibleAdapter
from app.domains.model_gateway.contracts import ProviderError, ProviderRequest

REQUEST = ProviderRequest(endpoint='https://model.test.invalid', api_key='test-only-key',
    model_id='deepseek-flash', system_prompt='Return a JSON object.', user_prompt='{"topic":"loss"}',
    connect_timeout_seconds=1, timeout_seconds=5, provider_kind='deepseek')

def response(content='{"answer":"ok"}', finish='stop', **fields):
    return {'model':'deepseek-flash','id':'synthetic-response',
        'choices':[{'finish_reason':finish,'message':{'content':content,**fields}}],
        'usage':{'prompt_tokens':30,'completion_tokens':10}}

@pytest.mark.parametrize('provider,mode,temperature',[('deepseek','disabled',True),('deepseek','enabled',False),('openai','enabled',True)])
def test_thinking_parameters_are_provider_specific(monkeypatch,provider,mode,temperature):
    captured={}
    def post(url,**kwargs):
        captured.update(kwargs['json']);return httpx.Response(200,json=response())
    monkeypatch.setattr(httpx,'post',post)
    result=OpenAICompatibleAdapter().invoke(replace(REQUEST,provider_kind=provider,thinking_mode=mode))
    assert ('temperature' in captured) is temperature
    assert captured.get('thinking') == ({'type':mode} if provider=='deepseek' else None)
    assert captured['model']=='deepseek-flash'
    assert captured['response_format']=={'type':'json_object'}
    assert result.metadata['response_model']=='deepseek-flash'
    assert result.input_tokens==30 and result.output_tokens==10

@pytest.mark.parametrize('payload,code,retryable',[
    (response('  '),'MODEL_PROVIDER_EMPTY',True),
    (response('{"answer":','length'),'MODEL_PROVIDER_TRUNCATED',False),
    (response(None,refusal='declined'),'MODEL_PROVIDER_REJECTED',False),
    (response('x'*262145),'MODEL_PROVIDER_RESPONSE_TOO_LARGE',False),
    ({'choices':[]},'MODEL_PROVIDER_PROTOCOL_INVALID',False),
])
def test_incomplete_and_unsafe_provider_results_are_explicit(monkeypatch,payload,code,retryable):
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:httpx.Response(200,json=payload))
    with pytest.raises(ProviderError) as result:OpenAICompatibleAdapter().invoke(REQUEST)
    assert result.value.code==code and result.value.retryable is retryable
    assert 'test-only-key' not in str(result.value)
    if code!='MODEL_PROVIDER_PROTOCOL_INVALID':assert result.value.metadata['output_tokens']==10

@pytest.mark.parametrize('status,code,retryable',[(429,'MODEL_PROVIDER_RATE_LIMITED',True),(503,'MODEL_PROVIDER_5XX',True),(401,'MODEL_PROVIDER_REJECTED',False)])
def test_provider_http_failures_are_classified_without_response_secrets(monkeypatch,status,code,retryable):
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:httpx.Response(status,text='private upstream detail',headers={'retry-after':'2'}))
    with pytest.raises(ProviderError) as result:OpenAICompatibleAdapter().invoke(REQUEST)
    assert result.value.code==code and result.value.retryable is retryable
    assert 'private upstream detail' not in str(result.value)

def test_timeout_is_bounded_and_invalid_json_is_left_for_schema_validation(monkeypatch):
    def timeout(*args,**kwargs):raise httpx.ReadTimeout('request timed out')
    monkeypatch.setattr(httpx,'post',timeout)
    with pytest.raises(ProviderError) as result:OpenAICompatibleAdapter().invoke(REQUEST)
    assert result.value.code=='MODEL_PROVIDER_TIMEOUT'
    monkeypatch.setattr(httpx,'post',lambda *args,**kwargs:httpx.Response(200,json=response('not JSON')))
    result=OpenAICompatibleAdapter().invoke(REQUEST)
    with pytest.raises(json.JSONDecodeError):json.loads(result.content)
