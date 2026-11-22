from app.lib.settings import get_settings

_settings = get_settings()

cors = _settings.app.get_cors_config()
alchemy = _settings.db.get_config()
