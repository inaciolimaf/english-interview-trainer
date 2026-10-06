from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    database_url: str = "postgresql+asyncpg://trainer:trainer@localhost:5432/trainer"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "deepseek/deepseek-v4.1-flash"
    # OpenRouter providers in order of preference (comma separated). Pinning matters: prompt
    # cache hits need requests to land on the same provider, and the default router picks the
    # cheapest (slow, fp4, no cache). Empty = let OpenRouter route freely.
    llm_providers: str = "together,deepinfra/fp8"
    model_server_url: str = "http://localhost:8001"
    whisper_model: str = "large-v3-turbo"
    whisper_compute_type: str = "int8"
    phoneme_model: str = "facebook/wav2vec2-xlsr-53-espeak-cv-ft"
    tts_voice: str = "af_heart"
    data_dir: Path = Path("./data")

    @property
    def data_path(self) -> Path:
        """DATA_DIR resolved against the repo root (not the process cwd)."""
        return self.data_dir if self.data_dir.is_absolute() else REPO_ROOT / self.data_dir


@lru_cache
def get_settings() -> Settings:
    return Settings()
