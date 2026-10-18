"""Claude as an AI source next to OpenAI and Ollama: every caller goes through services.ai.Chat, which turns one
message shape (text and base64 image parts) into each provider's own request. No network: the SDK clients are faked."""
import json
from types import SimpleNamespace as NS

import pytest
from flask import Flask

import database
from services import ai, food_vision

IMAGE = {'type': 'image', 'media_type': 'image/jpeg', 'data': 'QUJD'}


class FakeClaude:
    def __init__(self, text='ok', stop_reason='end_turn'):
        self.sent, self.text, self.stop_reason = {}, text, stop_reason
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kw):
        self.sent = kw
        return NS(stop_reason=self.stop_reason,
                  content=[NS(type='thinking', thinking=''), NS(type='text', text=self.text)])


class FakeOpenAI:
    def __init__(self, text='ok'):
        self.sent, self.text = {}, text
        self.chat = NS(completions=NS(create=self._create))

    def _create(self, **kw):
        self.sent = kw
        return NS(choices=[NS(message=NS(content=self.text))])


def _chat(provider, fake, model=None):
    chat = ai.make_chat(provider, openai_key='sk-x', claude_key='sk-ant-x', claude_model=model)
    chat._client = fake
    return chat


def test_claude_gets_its_own_image_blocks_and_no_temperature():
    fake = FakeClaude()
    reply = _chat('claude', fake)([{'role': 'user', 'content': [{'type': 'text', 'text': 'read'}, IMAGE]}],
                                  system='be brief', temperature=0, max_tokens=5)
    assert reply == 'ok'                                  # the thinking block is skipped
    sent = fake.sent
    assert sent['model'] == 'claude-opus-5-5' and sent['system'] == 'be brief'
    assert sent['messages'][0]['content'][1] == {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/jpeg', 'data': 'QUJD'}}
    assert 'temperature' not in sent                      # current Claude models reject it
    assert sent['max_tokens'] >= 16000                    # room for thinking as well as the reply
    assert sent['fallbacks'] == 'default' and sent['betas'] == ['server-side-fallback-2026-07-01']


def test_haiku_is_sent_without_fallbacks():
    fake = FakeClaude()
    _chat('claude', fake, 'claude-haiku-5-5')([{'role': 'user', 'content': 'hi'}])
    assert 'fallbacks' not in fake.sent and 'betas' not in fake.sent


def test_claude_json_is_unwrapped_from_a_code_fence():
    fake = FakeClaude('Here you go:\n```json\n{"items": [1, 2]}\n```')
    assert json.loads(_chat('claude', fake)([{'role': 'user', 'content': 'x'}], json=True)) == {'items': [1, 2]}


def test_a_claude_refusal_raises_rather_than_returning_empty_text():
    with pytest.raises(RuntimeError):
        _chat('claude', FakeClaude('', 'refusal'))([{'role': 'user', 'content': 'x'}])


def test_openai_gets_a_data_url_and_json_mode():
    fake = FakeOpenAI('{}')
    _chat('openai', fake)([{'role': 'user', 'content': [{'type': 'text', 'text': 'read'}, IMAGE]}],
                          system='sys', json=True, temperature=0)
    sent = fake.sent
    assert sent['messages'][0] == {'role': 'system', 'content': 'sys'}
    assert sent['messages'][1]['content'][1] == {'type': 'image_url', 'image_url': {'url': 'data:image/jpeg;base64,QUJD', 'detail': 'high'}}
    assert sent['response_format'] == {'type': 'json_object'} and sent['temperature'] == 0


def test_no_key_means_no_chat():
    assert ai.make_chat('claude', openai_key='sk-x') is None
    assert ai.make_chat('openai', claude_key='sk-ant-x') is None
    assert ai.make_chat('ollama').model == 'llama3.2'


def test_meal_photo_reader_works_through_claude(monkeypatch):
    from PIL import Image
    import io
    buf = io.BytesIO()
    Image.new('RGB', (20, 20), 'red').save(buf, 'PNG')
    fake = FakeClaude('```json\n' + json.dumps({'name': 'Beans on toast', 'confidence': 'high', 'items': [
        {'name': 'Beans', 'portion': '200 g', 'calories': 160, 'protein': 10, 'carbs': 26, 'fat': 1, 'fibre': 8}]}) + '\n```')
    monkeypatch.setattr(food_vision, 'get_chat', lambda: _chat('claude', fake))
    out = food_vision.estimate_meal(buf.getvalue())
    assert out['name'] == 'Beans on toast' and out['totals']['calories'] == 160
    image = fake.sent['messages'][0]['content'][1]
    assert image['type'] == 'image' and image['source']['media_type'] == 'image/jpeg'


@pytest.fixture
def app(tmp_path):
    app = Flask(__name__)
    app.config['DATABASE'] = str(tmp_path / 't.db')
    app.secret_key = 'test'
    app.teardown_appcontext(database.close_db)
    from routes.settings import bp
    app.register_blueprint(bp, url_prefix='/settings')
    with app.app_context():
        database.migrate_db()
        database.get_db().execute('INSERT OR IGNORE INTO Settings (id) VALUES (1)')
        database.get_db().commit()
    return app


def test_settings_keep_the_claude_key_and_errors_name_claude(app):
    c = app.test_client()
    c.post('/settings/', data={'aiProvider': 'claude', 'claudeKey': 'sk-ant-1', 'claudeModel': 'claude-sonnet-5-5'})
    c.post('/settings/', data={'aiProvider': 'claude', 'claudeKey': ''})          # blank: keep the saved key
    with app.app_context():
        s = database.query_db('SELECT aiProvider, claudeKey, claudeModel FROM Settings WHERE id=1', one=True)
        assert (s['aiProvider'], s['claudeKey'], s['claudeModel']) == ('claude', 'sk-ant-1', 'claude-sonnet-5-5')
        chat = ai.get_chat()
        assert (chat.provider, chat.model) == ('claude', 'claude-sonnet-5-5')
        database.get_db().execute("UPDATE Settings SET claudeKey=NULL WHERE id=1")
        assert ai.get_chat() is None
        assert 'Claude API key' in ai.missing_key_message()


def test_test_ai_button_uses_the_typed_claude_settings(app, monkeypatch):
    fake = FakeClaude()
    real = ai.make_chat

    def make(*a, **kw):
        chat = real(*a, **kw)
        chat._client = fake
        return chat
    monkeypatch.setattr(ai, 'make_chat', make)
    r = app.test_client().post('/settings/test-ai', data={'aiProvider': 'claude', 'claudeKey': 'sk-ant-typed',
                                                          'claudeModel': 'claude-haiku-5-5'})
    assert r.get_json()['model'] == 'claude-haiku-5-5' and fake.sent['model'] == 'claude-haiku-5-5'
    r = app.test_client().post('/settings/test-ai', data={'aiProvider': 'claude'})
    assert r.status_code == 400
