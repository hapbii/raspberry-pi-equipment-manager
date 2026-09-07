from pathlib import Path

from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")

from equipment_manager import create_app  # noqa: E402


app = create_app()
