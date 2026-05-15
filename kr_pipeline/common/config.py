import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    database_url: str
    test_database_url: str
    log_level: str

    @classmethod
    def load(cls) -> "Config":
        return cls(
            database_url=os.environ["DATABASE_URL"],
            test_database_url=os.environ.get("TEST_DATABASE_URL", ""),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
