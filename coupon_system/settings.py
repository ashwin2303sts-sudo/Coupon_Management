from pathlib import Path
import os
from dotenv import load_dotenv

# Load the XAMPP/MariaDB 10.4 compatibility patch before Django opens the DB.
from . import db_compat  # noqa: F401

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.getenv("SECRET_KEY", "change-this-secret-key-for-production")

DEBUG = os.getenv("DEBUG", "False").lower() == "true"

def env_list(name, default=""):
    return [item.strip() for item in os.getenv(name, default).split(",") if item.strip()]


ALLOWED_HOSTS = env_list("ALLOWED_HOSTS", "127.0.0.1,localhost")
render_host = os.getenv("RENDER_EXTERNAL_HOSTNAME", "").strip()
if render_host and render_host not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(render_host)

CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")
if render_host:
    render_origin = f"https://{render_host}"
    if render_origin not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(render_origin)

TIME_ZONE = "Asia/Kolkata"

INSTALLED_APPS = [
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
]

ROOT_URLCONF = "coupon_system.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]

WSGI_APPLICATION = "coupon_system.wsgi.application"

# MySQL / MariaDB / TiDB. Local XAMPP connections do not require TLS;
# remote database providers can enable it with MYSQL_SSL_MODE.
mysql_host = os.getenv("MYSQL_HOST", "127.0.0.1").strip()
db_options = {"charset": "utf8mb4"}
if mysql_host not in ("127.0.0.1", "localhost"):
    db_options["ssl_mode"] = os.getenv("MYSQL_SSL_MODE", "REQUIRED").strip() or "REQUIRED"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": os.getenv("MYSQL_DATABASE", "coupon_management"),
        "USER": os.getenv("MYSQL_USER", "root"),
        "PASSWORD": os.getenv("MYSQL_PASSWORD", ""),
        "HOST": mysql_host,
        "PORT": os.getenv("MYSQL_PORT", "3306"),
        "OPTIONS": db_options,
    }
}

# Keep authentication session lightweight; application records are stored in MySQL.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
if render_host:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

STATIC_URL = "/static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

DATA_DIR = BASE_DIR / "data"
MEDIA_ROOT = BASE_DIR / "media"
MEDIA_URL = "/media/"
