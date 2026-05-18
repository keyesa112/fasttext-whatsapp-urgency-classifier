from flask import current_app, jsonify, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from extensions import db
from models import User


PUBLIC_ENDPOINTS = {
    'auth.login',
    'auth.logout',
    'system.webhook',
    'system.health',
    'system.manifest',
    'static',
}
PUBLIC_API_PATHS = {
    '/api/webhook',
    '/api/webhooktes',
    '/api/internal/wa-mapping/pending',
    '/api/internal/wa-mapping/update',
}


def is_authenticated():
    return session.get('is_authenticated') is True


def is_api_request():
    return request.path.startswith('/api/')


def normalize_next_url(next_url):
    if next_url and next_url.startswith('/') and not next_url.startswith('//'):
        return next_url
    return url_for('pages.index')


def login_user(email):
    user = User.query.filter_by(email=email, is_active=True).first()

    session.clear()
    session.permanent = True
    session['is_authenticated'] = True
    session['user_email'] = email
    if user:
        session['user_id'] = user.id
        session['user_name'] = user.name


def logout_user():
    session.clear()


def credentials_match(email, password):
    user = User.query.filter_by(email=email).first()
    if not user or not user.is_active:
        return False

    return check_password_hash(user.password_hash, password)


def ensure_default_user():
    admin_email = current_app.config['ADMIN_EMAIL']
    admin_password = current_app.config['ADMIN_PASSWORD']
    admin_name = current_app.config['ADMIN_NAME']

    user = User.query.filter_by(email=admin_email).first()
    if user:
        updated = False

        if not user.name:
            user.name = admin_name
            updated = True

        if not user.role:
            user.role = 'admin'
            updated = True

        if not user.is_active:
            user.is_active = True
            updated = True

        if updated:
            db.session.commit()
        return user

    user = User(
        name=admin_name,
        email=admin_email,
        password_hash=generate_password_hash(admin_password),
        role='admin',
        is_active=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def require_login():
    if request.endpoint in PUBLIC_ENDPOINTS or request.path in PUBLIC_API_PATHS:
        return None

    if request.path.startswith('/static/'):
        return None

    if is_authenticated():
        session.permanent = True
        return None

    if is_api_request():
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    return redirect(url_for('auth.login', next=request.path))
