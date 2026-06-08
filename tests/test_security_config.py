import pytest

from app import app, validate_security_config


@pytest.fixture(autouse=True)
def restore_config():
    original = dict(app.config)
    yield
    app.config.clear()
    app.config.update(original)


def test_production_rejects_placeholder_credentials():
    app.config.update(
        TESTING=False,
        APP_ENV='production',
        SECRET_KEY='change-me-in-prod',
        ADMIN_PASSWORD='admin',
        STAFF_PASSWORD='staff',
    )

    with pytest.raises(RuntimeError, match='Unsafe placeholder configuration'):
        validate_security_config(app)


def test_testing_allows_placeholder_credentials():
    app.config.update(
        TESTING=True,
        APP_ENV='production',
        SECRET_KEY='change-me-in-prod',
        ADMIN_PASSWORD='admin',
        STAFF_PASSWORD='staff',
    )

    validate_security_config(app)
