from flask import Blueprint, render_template


pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
def index():
    return render_template('dashboard/index.html')


@pages_bp.route('/messages/queue')
def messages_queue():
    return render_template('messages/queue.html')


@pages_bp.route('/messages/detail/<int:message_id>')
def message_detail(message_id):
    return render_template('messages/detail.html', message_id=message_id)
