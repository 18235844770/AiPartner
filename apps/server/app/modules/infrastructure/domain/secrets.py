_SECRET_KEYS = {"api_key", "apikey", "password", "secret", "token", "authorization"}


def reject_secret_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).replace("-", "_").lower()
            if normalized in _SECRET_KEYS:
                raise ValueError("不能保存密钥")
            reject_secret_keys(item)
    elif isinstance(value, list):
        for item in value:
            reject_secret_keys(item)
