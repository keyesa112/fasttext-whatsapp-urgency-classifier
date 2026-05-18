from dotenv import load_dotenv
from flask import Flask

load_dotenv()

from config import Config
from extensions import db
from routes.auth import auth_bp
from routes.messages import messages_bp
from routes.pages import pages_bp
from routes.system import system_bp
from services.auth_service import ensure_default_user, require_login
from services.ml_service import ml_service


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    app.before_request(require_login)

    app.register_blueprint(auth_bp)
    app.register_blueprint(messages_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(system_bp)

    with app.app_context():
        db.create_all()
        ensure_default_user()
        try:
            ml_service.load(app.config['MODEL_PATH'])
        except Exception as exc:
            print(f"❌ Error loading model: {exc}")

    return app


app = create_app()


if __name__ == '__main__':
    print("✅ Database tables created/verified")
    app.run(debug=True, host='0.0.0.0', port=8080, threaded=True)
