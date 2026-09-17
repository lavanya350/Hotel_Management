from pathlib import Path
from uuid import uuid4

from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}


def save_image(file_storage):
    if not file_storage or not file_storage.filename:
        return None

    safe_name = secure_filename(file_storage.filename)
    ext = Path(safe_name).suffix.lower().lstrip(".")
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError("Allowed image types: PNG, JPG, JPEG, WEBP, GIF")

    filename = f"{uuid4().hex}.{ext}"
    file_storage.save(UPLOAD_DIR / filename)
    return filename


def delete_image(filename):
    if not filename:
        return
    path = UPLOAD_DIR / Path(filename).name
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass