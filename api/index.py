"""Entrypoint serverless ASGI untuk deployment Vercel."""

import logging

from edutrack.configs.app_config import AppConfig
from edutrack.main import seed_initial_data
from edutrack.web.api import create_app

logger = logging.getLogger(__name__)


def _build_vercel_app():
  config = AppConfig.from_env()
  application = create_app(config)
  if config.seed_demo_data:
    try:
      seed_initial_data(application.state.container)
    except Exception:  # pylint: disable=broad-except
      logger.exception("Gagal menjalankan seed_initial_data saat cold start Vercel.")
  return application


app = _build_vercel_app()
