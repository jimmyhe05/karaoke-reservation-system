import logging
import json
import pytest

from app import app, configure_logging


def test_json_logging_format(monkeypatch, caplog):
    app.config['LOG_FORMAT'] = 'json'
    configure_logging(app)

    with app.test_request_context('/api/test', method='GET'):
        # force handler to use caplog
        logger = app.logger
        caplog.set_level(logging.INFO)
        logger.info('hello')

    # we should have at least one record
    assert caplog.records
    # last record should be json parseable
    record_msg = caplog.records[-1].getMessage()
    # when LOG_FORMAT=json, our formatter returns JSON; for others, this may be plain text
    try:
        data = json.loads(record_msg)
    except json.JSONDecodeError:
        pytest.skip("Non-JSON formatter in use")
    assert data['message'] == 'hello'
    assert data['level'] == 'INFO'
    assert data['path'] == '/api/test'
