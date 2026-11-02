"""ASGI entry point: `uvicorn command_center.main:app`."""

from command_center.app import create_app

app = create_app()
