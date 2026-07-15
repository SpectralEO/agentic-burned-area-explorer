from functools import lru_cache
from pathlib import Path


def _default_workflow_skills_dir() -> Path:
    here = Path(__file__).resolve()
    candidates = [
        Path.cwd() / "workflow_skills",
        here.parents[1] / "workflow_skills",
        here.parents[2] / "workflow_skills",
        Path("/app/workflow_skills"),
        Path("/workflow_skills"),
    ]
    for candidate in candidates:
        if (candidate / "optical_imagery_finding" / "workflow.yaml").exists():
            return candidate
    return Path("/app/workflow_skills")

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
_REPO_DIR = _HERE.parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="WEA_",
        env_file=(
            _REPO_DIR / ".env",
            _BACKEND_DIR / ".env",
        ),
        env_ignore_empty=True,
        extra="ignore",
    )

    data_dir: Path = Path(__file__).parent / "data" / "demo"
    real_data_dir: Path = Path(__file__).parent / "data" / "real"
    db_path: Path = Path(__file__).parent / "data" / "investigations.sqlite"
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    workflow_skills_dir: Path = _default_workflow_skills_dir()
    stac_mode: str = "mock"  # mock | real | auto
    stac_provider: str = "earth-search"  # earth-search | planetary-computer
    stac_provider_order: str = ""  # comma-separated provider preference; empty uses sensor-aware defaults
    stac_api_url: str = "https://earth-search.aws.element84.com/v1"
    stac_earth_search_api_url: str = "https://earth-search.aws.element84.com/v1"
    stac_planetary_computer_api_url: str = "https://planetarycomputer.microsoft.com/api/stac/v1"
    stac_timeout_seconds: int = 20
    stac_max_items: int = 8
    stac_modis_api_url: str | None = None
    stac_modis_collections: str | None = None
    cdse_username: str | None = Field(default=None, validation_alias=AliasChoices("CDSE_USERNAME", "WEA_CDSE_USERNAME"))
    cdse_password: str | None = Field(default=None, validation_alias=AliasChoices("CDSE_PASSWORD", "WEA_CDSE_PASSWORD"))
    cdse_client_id: str | None = Field(default="cdse-public", validation_alias=AliasChoices("CDSE_CLIENT_ID", "WEA_CDSE_CLIENT_ID"))
    cdse_client_secret: str | None = Field(default=None, validation_alias=AliasChoices("CDSE_CLIENT_SECRET", "WEA_CDSE_CLIENT_SECRET"))
    ba300_auto_sync: bool = Field(default=False, validation_alias=AliasChoices("BA300_AUTO_SYNC", "WEA_BA300_AUTO_SYNC"))
    ba300_source_mode: str = Field(default="auto", validation_alias=AliasChoices("BA300_SOURCE_MODE", "WEA_BA300_SOURCE_MODE"))
    ba300_stac_collection: str = Field(default="clms_ba_global_300m_monthly_v4_cog", validation_alias=AliasChoices("BA300_STAC_COLLECTION", "WEA_BA300_STAC_COLLECTION"))
    ba300_byoc_collection_id: str = Field(default="b8b617c6-182f-427e-a86c-23fc36ac6098", validation_alias=AliasChoices("BA300_BYOC_COLLECTION_ID", "WEA_BA300_BYOC_COLLECTION_ID"))
    planetary_computer_sign_url: str = "https://planetarycomputer.microsoft.com/api/sas/v1/sign"
    api_public_base: str = "http://localhost:8000/api"
    imagery_render_mode: str = "tiler"  # tiler | preview
    tiler_public_base: str = "http://localhost:8001"
    tiler_internal_base: str = "http://localhost:8001"
    agent_mode: str = "rule_based"

    @property
    def origins(self) -> list[str]:
        return [x.strip() for x in self.allowed_origins.split(",") if x.strip()]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not (settings.workflow_skills_dir / "optical_imagery_finding" / "workflow.yaml").exists():
        settings.workflow_skills_dir = _default_workflow_skills_dir()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    settings.real_data_dir.mkdir(parents=True, exist_ok=True)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    return settings
