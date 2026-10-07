from dataclasses import dataclass
import os
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///./certificates.db"
    generated_files_dir: Path = PROJECT_ROOT / "generated"
    template_path: Path = PROJECT_ROOT / "templates" / "certificate_template.pdf"
    organization_name: str = "TECH ACADEMY"

    @classmethod
    def from_environment(cls) -> "Settings":
        load_dotenv(PROJECT_ROOT / ".env", override=False)
        return cls(
            database_url=os.getenv("DATABASE_URL", "sqlite:///./certificates.db"),
            generated_files_dir=Path(
                os.getenv("GENERATED_FILES_DIR", str(PROJECT_ROOT / "generated"))
            ).expanduser().resolve(),
            template_path=Path(
                os.getenv(
                    "TEMPLATE_PATH",
                    str(PROJECT_ROOT / "templates" / "certificate_template.pdf"),
                )
            ).expanduser().resolve(),
            organization_name=os.getenv("ORGANIZATION_NAME", "TECH ACADEMY").strip()
            or "TECH ACADEMY",
        )
