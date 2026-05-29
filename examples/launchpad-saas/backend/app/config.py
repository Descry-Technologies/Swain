from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    jwt_secret: str = "dev-secret-change-before-launch"
    default_admin_email: str = "founder@example.test"
    default_admin_password: str = "changeme"
    stripe_webhook_secret: str = "whsec_demo_replace_me"


settings = Settings()
