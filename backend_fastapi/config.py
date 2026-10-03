import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_NAME: str = "Duxue Space System API"
    DATABASE_URL: str = "sqlite:///./duxue.db"  # 初期开发使用SQLite，后续部署直接修改为MySQL链接即可
    SECRET_KEY: str = "duxue-super-secret-jwt-key"  
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 * 7  # Token有效期7天，减少频繁登录

    # AI与第三方接口配置
    AI_API_KEY: str = os.getenv("AI_API_KEY", "")
    AI_MODEL_NAME: str = "deepseek-chat" # 预设模型
    ADMIN_IDAGONG_COOKIE: str = os.getenv("ADMIN_IDAGONG_COOKIE", "") # 管理员爱大工JSESSIONID

settings = Settings()