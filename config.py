import os
from datetime import timedelta


class Config:
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.getenv('SECRET_KEY') or 'k24-kalibutuh-session-secret'
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.getenv('FLASK_ENV') == 'production'

    ADMIN_NAME = os.getenv('ADMIN_NAME', 'Admin K24').strip()
    ADMIN_EMAIL = os.getenv('ADMIN_EMAIL', 'k24kalibutuh@email.com').strip().lower()
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'k24kalibutuh')
    MODEL_PATH = os.getenv(
        'FASTTEXT_MODEL_PATH',
        '/Users/spc/Documents/apotek_whatsapp/model/basic_model_v.1.3.bin',
    )
