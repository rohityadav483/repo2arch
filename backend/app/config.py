"""
config.py
---------
Central configuration module for Repo2Arch backend.
All environment variables are loaded here via pydantic-settings.
Import `settings` anywhere in the app — never read os.environ directly.
"""

import os
from functools import lru_cache
from pydantic_settings import BaseSettings
from pydantic import Field, validator


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Falls back to .env file when running locally.
    """

    # ------------------------------------------------------------------ #
    # App meta                                                             #
    # ------------------------------------------------------------------ #
    APP_NAME: str = "Repo2Arch"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, env="DEBUG")

    # ------------------------------------------------------------------ #
    # Hugging Face Inference API                                           #
    # ------------------------------------------------------------------ #
    HF_API_KEY: str = Field(default="", env="HF_API_KEY")
    GROQ_API_KEY: str = Field(..., env="GROQ_API_KEY")
    # Default model — can be overridden per-request
    HF_MODEL: str = Field(
        default="HuggingFaceH4/zephyr-7b-beta",
        env="HF_MODEL",
    )

    HF_FALLBACK_MODELS: list[str] = [
        "mistralai/Mistral-7B-Instruct-v0.3",
        "Qwen/Qwen2.5-72B-Instruct",
    ]

    # Maximum new tokens to generate per summary request
    HF_MAX_NEW_TOKENS: int = Field(default=512, env="HF_MAX_NEW_TOKENS")

    # ------------------------------------------------------------------ #
    # Supabase                                                             #
    # ------------------------------------------------------------------ #
    SUPABASE_URL: str = Field(..., env="SUPABASE_URL")
    SUPABASE_KEY: str = Field(..., env="SUPABASE_KEY")

    # Table names — centralised so a rename only touches this file
    SUPABASE_TABLE_ANALYSES: str = "analyses"
    SUPABASE_TABLE_DIAGRAMS: str = "diagrams"

    # ------------------------------------------------------------------ #
    # GitHub / repo fetching                                               #
    # ------------------------------------------------------------------ #
    # Local directory where repos are temporarily cloned
    REPO_CLONE_DIR: str = Field(
        default="/tmp/repo2arch_clones",
        env="REPO_CLONE_DIR",
    )

    # Directories to skip during file traversal
    IGNORED_DIRS: list[str] = [
        "node_modules",
        "venv",
        ".venv",
        "dist",
        "build",
        ".git",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        "coverage",
        ".next",
        ".nuxt",
    ]

    # File extensions we actually want to read
    SUPPORTED_EXTENSIONS: list[str] = [
        ".py",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
        ".json",
        ".toml",
        ".yaml",
        ".yml",
        ".txt",          # requirements.txt etc.
        ".cfg",
        ".ini",
        ".md",
    ]

    # Max file size to read (bytes) — skips large generated files
    MAX_FILE_SIZE_BYTES: int = 200_000   # 200 KB

    # ------------------------------------------------------------------ #
    # CORS origins allowed to call the FastAPI backend                    #
    # ------------------------------------------------------------------ #
    ALLOWED_ORIGINS: list[str] = Field(
        default=["http://localhost:8501", "http://127.0.0.1:8501"],
        env="ALLOWED_ORIGINS",
    )

    # ------------------------------------------------------------------ #
    # Pydantic config                                                      #
    # ------------------------------------------------------------------ #
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = True

    # ------------------------------------------------------------------ #
    # Derived helpers                                                      #
    # ------------------------------------------------------------------ #
    @validator("REPO_CLONE_DIR", pre=True, always=True)
    def ensure_clone_dir_exists(cls, v: str) -> str:
        """Create the clone directory on startup if it does not exist."""
        os.makedirs(v, exist_ok=True)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Return a cached singleton Settings instance.
    Use this everywhere:
        from app.config import get_settings
        settings = get_settings()
    """
    return Settings()


# Convenience alias — import `settings` directly for brevity
settings: Settings = get_settings()
