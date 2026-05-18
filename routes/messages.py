from collections import Counter
from datetime import datetime, timedelta

from flask import Blueprint, jsonify, request

from extensions import db
from models import Customer, Message
from services.sse_service import broadcast_event


messages_bp = Blueprint('messages', __name__)

INTENT_PRIORITY = {'urgent': 3, 'normal': 2, 'non_urgent': 1}


def resolve_group_intent(messages):
    intent_counts = Counter(message.intent for message in messages if message.intent)
    if not intent_counts:
        return 'non_urgent'

    return max(
        intent_counts.items(),
        key=lambda item: (item[1], INTENT_PRIORITY.get(item[0], 0)),
    )[0]


@messages_bp.route('/api/messages/urgent')
def get_urgent_messages():
    notification_window = datetime.now() - timedelta(minutes=30)

    recent_notified = db.session.query(Message.customer_id).filter(
        Message.notified.is_(True),
        Message.last_notified_at >= notification_window,
        Message.status.in_(['pending', 'in_progress']),
    ).distinct()

    messages = Message.query.filter(
        Message.intent == 'urgent',
        Message.status.in_(['pending', 'in_progress']),
        ~Message.customer_id.in_(recent_notified),
    ).order_by(Message.timestamp.desc()).all()

    customer_messages = {}
    for msg in messages:
        if msg.customer_id not in customer_messages:
            msg_count = Message.query.filter(
                Message.customer_id == msg.customer_id,
                Message.timestamp >= notification_window,
                Message.status.in_(['pending', 'in_progress']),
            ).count()
            customer_messages[msg.customer_id] = {'message': msg, 'count': msg_count}

    filtered_messages = [value['message'] for value in customer_messages.values()]

    return jsonify(
        {
            'new_urgent_count': len(filtered_messages),
            'messages': [
                {
                    'id': m.id,
                    'customer': {
                        'id': m.customer.id,
                        'phone': m.customer.phone,
                        'name': m.customer.name,
                    },
                    'message_text': m.message_text,
                    'intent': m.intent,
                    'confidence': m.confidence,
                    'timestamp': m.timestamp.isoformat(),
                    'is_handled': m.is_handled,
                    'status': m.status,
                    'message_count': customer_messages[m.customer_id]['count'],
                }
                for m in filtered_messages
            ],
        }
    ), 200


@messages_bp.route('/api/messages/mark-notified', methods=['POST'])
def mark_notified():
    data = request.json or {}
    message_ids = data.get('message_ids', [])

    if not message_ids:
        return jsonify({'status': 'error', 'message': 'No message IDs'}), 400

    now = datetime.now()
    updated = Message.query.filter(Message.id.in_(message_ids)).update(
        {Message.notified: True, Message.last_notified_at: now},
        synchronize_session=False,
    )
    db.session.commit()

    return jsonify({'status': 'ok', 'updated_count': updated, 'timestamp': now.isoformat()}), 200


@messages_bp.route('/api/messages/queue')
def get_queue():
    intent = request.args.get('intent')
    status_filter = request.args.get('status', 'pending')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    search = request.args.get('search', '').strip()

    if page < 1:
        page = 1
    if per_page < 1 or per_page > 100:
        per_page = 20

    query = Message.query.join(Customer).filter(Message.status == status_filter)

    if search:
        search_pattern = f'%{search}%'
        query = query.filter(
            db.or_(
                Customer.phone.like(search_pattern),
                Customer.name.like(search_pattern),
                Message.message_text.like(search_pattern),
            )
        )

    grouped_messages = {}
    messages = query.order_by(Message.timestamp.desc(), Message.id.desc()).all()

    for message in messages:
        grouped_messages.setdefault(message.customer_id, []).append(message)

    grouped_result = []
    for customer_messages in grouped_messages.values():
        latest_message = customer_messages[0]
        group_intent = resolve_group_intent(customer_messages)

        if intent and group_intent != intent:
            continue

        grouped_result.append(
            {
                'id': latest_message.id,
                'customer': {
                    'id': latest_message.customer.id,
                    'phone': latest_message.customer.phone,
                    'name': latest_message.customer.name,
                },
                'message_text': latest_message.message_text[:80] + '...'
                if len(latest_message.message_text) > 80
                else latest_message.message_text,
                'intent': group_intent,
                'confidence': latest_message.confidence,
                'timestamp': latest_message.timestamp.isoformat(),
                'status': latest_message.status,
                'message_count': len(customer_messages),
            }
        )

    grouped_result.sort(key=lambda item: item['timestamp'], reverse=True)

    total = len(grouped_result)
    offset = (page - 1) * per_page
    result = grouped_result[offset:offset + per_page]

    return jsonify({'total': total, 'page': page, 'per_page': per_page, 'messages': result}), 200


@messages_bp.route('/api/messages/<int:message_id>')
def get_message_detail(message_id):
    message = Message.query.get_or_404(message_id)
    return jsonify(
        {
            'id': message.id,
            'customer': {
                'id': message.customer.id,
                'phone': message.customer.phone,
                'name': message.customer.name,
            },
            'message_text': message.message_text,
            'intent': message.intent,
            'confidence': message.confidence,
            'timestamp': message.timestamp.isoformat(),
            'is_handled': message.is_handled,
            'status': message.status,
            'notified': message.notified,
            'whatsapp_link': f"https://wa.me/{message.customer.phone}",
        }
    ), 200


@messages_bp.route('/api/messages/<int:message_id>/status', methods=['PUT'])
def update_message_status(message_id):
    data = request.json or {}
    new_status = data.get('status')

    if new_status not in ['pending', 'in_progress', 'completed']:
        return jsonify({'status': 'error', 'message': 'Invalid status'}), 400

    message = Message.query.get_or_404(message_id)
    message.status = new_status
    message.is_handled = new_status == 'completed'
    db.session.commit()

    broadcast_event('status_changed', {'message_id': message_id, 'new_status': new_status})

    return jsonify(
        {
            'status': 'ok',
            'message_id': message_id,
            'new_status': new_status,
            'is_handled': message.is_handled,
        }
    ), 200


@messages_bp.route('/api/messages/customer/<int:customer_id>/status', methods=['PUT'])
def update_customer_status(customer_id):
    data = request.json or {}
    new_status = data.get('status')

    print(f"🔧 UPDATE STATUS - Customer: {customer_id}, New Status: {new_status}")

    if new_status not in ['pending', 'in_progress', 'completed']:
        return jsonify({'error': 'Invalid status'}), 400

    try:
        sample_msg = Message.query.filter(Message.customer_id == customer_id).order_by(Message.timestamp.desc()).first()
        if not sample_msg:
            return jsonify({'message': 'No messages found', 'updated_count': 0}), 200

        messages = Message.query.filter(
            Message.customer_id == customer_id,
            Message.status != 'completed',
        ).all()

        updated_count = 0
        for msg in messages:
            msg.status = new_status
            msg.is_handled = new_status == 'completed'
            updated_count += 1

        db.session.commit()
        print(f"✅ Updated {updated_count} messages to {new_status}")

        broadcast_event(
            'status_changed',
            {
                'customer_id': customer_id,
                'new_status': new_status,
                'updated_count': updated_count,
            },
        )

        return jsonify(
            {
                'message': f'Updated {updated_count} messages to {new_status}',
                'updated_count': updated_count,
                'customer_id': customer_id,
                'new_status': new_status,
            }
        ), 200
    except Exception as exc:
        db.session.rollback()
        print(f"❌ Error: {str(exc)}")
        return jsonify({'error': str(exc)}), 500


@messages_bp.route('/api/messages/<int:message_id>/handle', methods=['PUT'])
def handle_message(message_id):
    message = Message.query.get_or_404(message_id)
    message.is_handled = True
    message.status = 'completed'
    db.session.commit()
    return jsonify({'status': 'ok', 'message_id': message_id}), 200


@messages_bp.route('/api/messages/customer/<int:customer_id>')
def get_customer_messages(customer_id):
    limit = request.args.get('limit', 10, type=int)
    time_window = datetime.now() - timedelta(minutes=30)

    messages = Message.query.filter(Message.customer_id == customer_id).order_by(Message.timestamp.desc()).limit(limit).all()
    urgent_count = Message.query.filter(
        Message.customer_id == customer_id,
        Message.intent == 'urgent',
        Message.timestamp >= time_window,
    ).count()

    return jsonify(
        {
            'total_messages': len(messages),
            'urgent_count': urgent_count,
            'messages': [
                {
                    'id': m.id,
                    'message_text': m.message_text,
                    'intent': m.intent,
                    'confidence': m.confidence,
                    'timestamp': m.timestamp.isoformat(),
                    'is_handled': m.is_handled,
                    'status': m.status,
                    'notified': m.notified,
                }
                for m in messages
            ],
        }
    ), 200


@messages_bp.route('/api/messages/customer/<int:customer_id>/handle-all', methods=['PUT'])
def handle_all_customer_messages(customer_id):
    updated = Message.query.filter(
        Message.customer_id == customer_id,
        Message.status != 'completed',
    ).update({Message.is_handled: True, Message.status: 'completed'}, synchronize_session=False)
    db.session.commit()

    return jsonify({'status': 'ok', 'customer_id': customer_id, 'handled_count': updated}), 200
