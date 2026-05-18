from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from services.auth_service import credentials_match, is_authenticated, login_user, logout_user, normalize_next_url


auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if is_authenticated():
        return redirect(url_for('pages.index'))

    next_url = normalize_next_url(request.args.get('next') or request.form.get('next'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''

        if credentials_match(email, password):
            login_user(current_app.config['ADMIN_EMAIL'])
            return redirect(next_url)

        flash('Email atau password salah.', 'error')

    return render_template(
        'auth/login.html',
        next_url=next_url,
        admin_email=current_app.config['ADMIN_EMAIL'],
    )


@auth_bp.route('/logout', methods=['POST'])
def logout():
    logout_user()
    flash('Berhasil logout.', 'success')
    return redirect(url_for('auth.login'))
