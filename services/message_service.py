from datetime import datetime, timedelta

from extensions import db
from models import Customer, Message
from services.ml_service import ml_service
from services.sse_service import broadcast_event


def parse_timestamp(timestamp_str):
    if not timestamp_str:
        return datetime.now()

    if isinstance(timestamp_str, (int, float)):
        try:
            return datetime.fromtimestamp(timestamp_str)
        except Exception:
            return datetime.now()

    try:
        return datetime.fromisoformat(str(timestamp_str).replace('Z', '+00:00'))
    except ValueError:
        try:
            return datetime.strptime(str(timestamp_str), '%Y-%m-%d %H:%M:%S')
        except ValueError:
            print(f"⚠️ Invalid timestamp: {timestamp_str}")
            return datetime.now()


def extract_webhook_fields(data):
    sender = (
        data.get('pengirim')
        or data.get('sender')
        or data.get('from')
        or data.get('phone')
        or data.get('number')
    )
    message_text = (
        data.get('pesan')
        or data.get('message')
        or data.get('text')
        or data.get('body')
        or data.get('msg')
    )
    name = (
        data.get('name')
        or data.get('pushname')
        or data.get('contact')
        or data.get('sender_name')
        or 'Unknown'
    )
    return sender, message_text, name


def find_recent_duplicate(customer_id, message_text):
    time_window = datetime.now() - timedelta(minutes=5)
    return Message.query.filter(
        Message.customer_id == customer_id,
        Message.message_text == message_text,
        Message.timestamp >= time_window,
    ).first()


def save_incoming_message(data):
    sender, message_text, name = extract_webhook_fields(data)
    if not sender or not message_text:
        return None, {
            'status': 'error',
            'message': 'Missing required fields: pengirim/sender, pesan/message',
            'received_keys': list(data.keys()),
        }, 400

    customer = Customer.query.filter_by(phone=sender).first()
    if not customer:
        customer = Customer(phone=sender, name=name)
        db.session.add(customer)
        db.session.flush()

    duplicate = find_recent_duplicate(customer.id, message_text)
    if duplicate:
        return duplicate, {
            'status': 'duplicate',
            'message': 'Pesan sudah diproses dalam 5 menit terakhir',
            'existing_message_id': duplicate.id,
            'original_timestamp': duplicate.timestamp.isoformat(),
        }, 200

    intent, confidence = ml_service.predict(message_text)
    msg_timestamp = parse_timestamp(data.get('timestamp'))

    message = Message(
        customer_id=customer.id,
        message_text=message_text,
        intent=intent,
        confidence=confidence,
        timestamp=msg_timestamp,
        status='pending',
    )
    db.session.add(message)
    db.session.commit()

    broadcast_event(
        'new_message',
        {
            'intent': intent,
            'count': 1,
            'preview': message_text[:60],
            'customer_name': customer.name,
            'message_id': message.id,
        },
    )

    return message, {
        'status': 'ok',
        'data': {
            'message_id': message.id,
            'name': customer.name,
            'pengirim': customer.phone,
            'pesan': message_text,
            'intent': intent,
            'confidence': confidence,
            'timestamp': msg_timestamp.isoformat(),
        },
    }, 200
