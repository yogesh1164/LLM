from pydantic import SecretStr

from app.config import Settings


def test_api_access_token_loads_from_env_file_and_is_redacted(tmp_path) -> None:
    token = "regression-test-token-value-1234567890"
    env_file = tmp_path / ".env"
    env_file.write_text(f"API_ACCESS_TOKEN={token}\n", encoding="utf-8")

    config = Settings(_env_file=env_file)

    assert config.api_access_token == SecretStr(token)
    assert token not in repr(config)
    assert "**********" in repr(config)
