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
    # TLS (port 8883) for a private broker such as HiveMQ Cloud; uses the OS CA store
    mqtt_tls: bool = False
    # Tao du lieu demo (thiet bi, luat, 12 gio du lieu gia) khi database trong
    seed_demo: bool = False

    # ---- Cloud time-series sink (Influx line protocol: Grafana Cloud or InfluxDB) ----
    cloud_sink_enabled: bool = False
    cloud_sink_url: str = ""
    # Set for Grafana Cloud (Basic auth); leave empty for InfluxDB (Token auth)
    cloud_sink_user: str = ""
    cloud_sink_token: str = ""
    cloud_sink_interval: float = 10.0
    cloud_sink_max_buffer: int = 10000

    # ---- Local analytics pipeline ----
    lake_dir: str = "data/lake"
    raw_retention_days: int = 7
    anomaly_z: float = 3.0

    # ---- Dashboard login (empty password = open dashboard, as before) ----
    dashboard_password: str = ""
    # Empty = random secret per process, so tokens expire on restart
    auth_secret: str = ""
    auth_token_hours: float = 12.0

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
