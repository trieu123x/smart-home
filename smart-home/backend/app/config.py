from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Cau hinh doc tu file .env (hoac bien moi truong)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./smarthome.db"
    # Khoa ma ESP32 phai gui kem trong header X-Device-Key khi day du lieu len
    device_api_key: str = "esp32-secret-key"
    cors_origins: str = "http://localhost:3000"

    # ---- MQTT: cau noi voi ESP32 (cung giao thuc voi ban Django) ----
    mqtt_enabled: bool = True
    mqtt_host: str = "broker.hivemq.com"
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_pass: str = ""
    mqtt_prefix: str = "ptit_sh_k7x2q9/home/"
    mqtt_offline_after: float = 6.0
    mqtt_history_seconds: float = 10.0
    # Tao du lieu demo (thiet bi, luat, 12 gio du lieu gia) khi database trong
    seed_demo: bool = False

    @property
    def mqtt_topic_prefix(self) -> str:
        return self.mqtt_prefix if self.mqtt_prefix.endswith("/") else self.mqtt_prefix + "/"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
