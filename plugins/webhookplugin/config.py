from pydantic import BaseModel


class Config(BaseModel):
    """Plugin Config Here"""
    webhook_host: str = "0.0.0.0"
    webhook_port: int = 8000
