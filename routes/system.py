from datetime import datetime
from collections import Counter

from flask import Blueprint, jsonify, request, send_from_directory

from extensions import db
from models import Customer, Message
from services.message_service import save_incoming_message
from services.ml_service import ml_service
from services.sse_service import broadcast_event, listener_count, stream_response


system_bp = Blueprint('system', __name__)
INTENT_PRIORITY = {'urgent': 3, 'normal': 2, 'non_urgent': 1}


def normalize_phone(remote_jid):
    if not remote_jid:
        return None

    phone = str(remote_jid).split('@', 1)[0]
    normalized = ''.join(ch for ch in phone if ch.isdigit())
    return normalized or None


def normalize_jid(value):
    if not value:
        return None
    return str(value).strip()


def extract_wa_message_text(payload):
    message = payload.get('message') or {}
    return (
        message.get('conversation')
        or (message.get('extendedTextMessage') or {}).get('text')
        or (message.get('imageMessage') or {}).get('caption')
        or (message.get('videoMessage') or {}).get('caption')
        or ''
    ).strip()


def resolve_group_intent(messages):
    intent_counts = Counter(message.intent for message in messages if message.intent)
    if not intent_counts:
        return 'non_urgent'

    return max(
        intent_counts.items(),
        key=lambda item: (item[1], INTENT_PRIORITY.get(item[0], 0)),
    )[0]


def get_active_customer_messages(customer_id):
    return Message.query.filter(
        Message.customer_id == customer_id,
        Message.status.in_(['pending', 'in_progress']),
    ).order_by(Message.timestamp.desc(), Message.id.desc()).all()


def build_customer_ticket_state(customer):
    active_messages = get_active_customer_messages(customer.id)
    active_intent_counts = {'urgent': 0, 'normal': 0, 'non_urgent': 0}
    group_label = None

    if active_messages:
        group_label = resolve_group_intent(active_messages)
        for msg in active_messages:
            if msg.intent in active_intent_counts:
                active_intent_counts[msg.intent] += 1

    return {
        'active_messages': active_messages,
        'active_message_count': len(active_messages),
        'active_intent_counts': active_intent_counts,
        'group_label': group_label,
    }


def find_customer_by_phone(phone):
    if not phone:
        return None
    return Customer.query.filter_by(phone=phone).first()


def find_customer_by_identifiers(phone=None, pn_jid=None, lid_jid=None):
    normalized_phone = normalize_phone(phone) if phone else None
    normalized_pn_jid = normalize_jid(pn_jid)
    normalized_lid_jid = normalize_jid(lid_jid)

    if normalized_phone:
        customer = find_customer_by_phone(normalized_phone)
        if customer:
            return customer

    filters = []
    if normalized_pn_jid:
        filters.append(Customer.wa_pn_jid == normalized_pn_jid)
    if normalized_lid_jid:
        filters.append(Customer.wa_lid_jid == normalized_lid_jid)

    if not filters:
        return None

    return Customer.query.filter(db.or_(*filters)).first()


def persist_customer_mapping(customer, phone=None, pn_jid=None, lid_jid=None):
    if not customer:
        return False

    changed = False
    normalized_phone = normalize_phone(phone) if phone else None
    normalized_pn_jid = normalize_jid(pn_jid)
    normalized_lid_jid = normalize_jid(lid_jid)

    if normalized_phone and not customer.phone:
        customer.phone = normalized_phone
        changed = True

    if normalized_pn_jid and customer.wa_pn_jid != normalized_pn_jid:
        customer.wa_pn_jid = normalized_pn_jid
        changed = True

    if normalized_lid_jid and customer.wa_lid_jid != normalized_lid_jid:
        customer.wa_lid_jid = normalized_lid_jid
        changed = True

    if changed:
        customer.wa_mapping_updated_at = datetime.now()

    return changed


def is_baileys_outgoing_event(data):
    payload = data.get('data') or {}
    key = payload.get('key') or {}
    event = data.get('event')
    return bool(key.get('remoteJid')) and (
        bool(key.get('fromMe'))
        or event in {'message:out:new', 'message:out:update', 'message:out:ack'}
    )


def is_baileys_incoming_event(data):
    payload = data.get('data') or {}
    key = payload.get('key') or {}
    return bool(key.get('remoteJid')) and not is_baileys_outgoing_event(data)


def process_baileys_outgoing(data):
    payload = data.get('data') or {}
    key = payload.get('key') or {}
    remote_jid = normalize_jid(key.get('remoteJid'))
    resolved = data.get('resolved') or {}
    resolved_phone = resolved.get('phone')
    resolved_pn_jid = resolved.get('wa_pn_jid') or resolved.get('pn_jid')
    resolved_lid_jid = resolved.get('wa_lid_jid') or resolved.get('lid_jid')

    customer = find_customer_by_identifiers(
        phone=resolved_phone or remote_jid,
        pn_jid=resolved_pn_jid or remote_jid,
        lid_jid=resolved_lid_jid or remote_jid,
    )
    if not customer:
        return {'status': 'outgoing_ok', 'updated_count': 0, 'message': 'Customer not found'}, 200

    mapping_changed = persist_customer_mapping(
        customer,
        phone=resolved_phone or customer.phone,
        pn_jid=resolved_pn_jid,
        lid_jid=resolved_lid_jid if resolved_lid_jid else (remote_jid if remote_jid and remote_jid.endswith('@lid') else None),
    )
    if mapping_changed:
        db.session.commit()

    ticket_state = build_customer_ticket_state(customer)
    eligible_for_auto_close = ticket_state['group_label'] == 'urgent'

    if not eligible_for_auto_close:
        return {
            'status': 'outgoing_ok',
            'updated_count': 0,
            'customer_id': customer.id,
            'auto_close_rule': 'outgoing only + group label must be urgent',
            'group_label': ticket_state['group_label'],
            'mapping_updated': mapping_changed,
            'message': 'Ticket is not eligible for auto close',
        }, 200

    updated = Message.query.filter(
        Message.customer_id == customer.id,
        Message.status.in_(['pending', 'in_progress']),
    ).update(
        {
            Message.status: 'completed',
            Message.is_handled: True,
        },
        synchronize_session=False,
    )
    db.session.commit()

    if updated:
        broadcast_event(
            'status_changed',
            {
                'customer_id': customer.id,
                'new_status': 'completed',
                'updated_count': updated,
                'intent': 'urgent',
                'group_label': ticket_state['group_label'],
            },
        )

    return {
        'status': 'outgoing_ok',
        'updated_count': updated,
        'customer_id': customer.id,
        'auto_close_rule': 'outgoing only + group label must be urgent',
        'group_label': ticket_state['group_label'],
        'mapping_updated': mapping_changed,
    }, 200


def process_baileys_incoming(data):
    if not ml_service.is_ready():
        return {'status': 'error', 'message': 'Model not loaded'}, 503

    payload = data.get('data') or {}
    key = payload.get('key') or {}
    remote_jid = key.get('remoteJid')
    phone = normalize_phone(remote_jid) if remote_jid else None

    if not phone:
        return {'status': 'ignored', 'message': 'Invalid remoteJid'}, 200

    customer = find_customer_by_phone(phone)
    if customer:
        mapping_changed = persist_customer_mapping(
            customer,
            phone=phone,
            pn_jid=remote_jid if remote_jid and remote_jid.endswith('@s.whatsapp.net') else None,
        )
        if mapping_changed:
            db.session.commit()

    message_text = extract_wa_message_text(payload)
    if not message_text:
        return {'status': 'ignored', 'message': 'Empty incoming message'}, 200

    incoming_data = {
        'sender': phone,
        'message': message_text,
        'name': (
            payload.get('pushName')
            or payload.get('notifyName')
            or data.get('pushName')
            or data.get('name')
            or 'Unknown'
        ),
        'timestamp': payload.get('messageTimestamp') or data.get('timestamp'),
    }

    _, response_payload, status_code = save_incoming_message(incoming_data)
    return {'status': 'incoming_ok', 'result': response_payload}, status_code


@system_bp.route('/api/internal/wa-mapping/pending')
def get_pending_wa_mappings():
    limit = request.args.get('limit', 20, type=int)
    if limit < 1:
        limit = 20
    if limit > 100:
        limit = 100

    customers = Customer.query.filter(
        db.or_(
            Customer.wa_lid_jid.is_(None),
            Customer.wa_lid_jid == '',
        )
    ).order_by(Customer.created_at.desc(), Customer.id.desc()).limit(limit).all()

    return jsonify(
        {
            'status': 'ok',
            'count': len(customers),
            'customers': [
                {
                    'id': customer.id,
                    'phone': customer.phone,
                    'name': customer.name,
                    'wa_pn_jid': customer.wa_pn_jid,
                    'wa_lid_jid': customer.wa_lid_jid,
                    'wa_mapping_updated_at': (
                        customer.wa_mapping_updated_at.isoformat()
                        if customer.wa_mapping_updated_at
                        else None
                    ),
                }
                for customer in customers
            ],
        }
    ), 200


@system_bp.route('/api/internal/wa-mapping/update', methods=['POST'])
def update_wa_mapping():
    data = request.get_json(silent=True) or {}
    customer_id = data.get('customer_id')
    phone = data.get('phone')
    pn_jid = data.get('wa_pn_jid') or data.get('pn_jid')
    lid_jid = data.get('wa_lid_jid') or data.get('lid_jid')

    customer = None
    if customer_id:
        customer = Customer.query.get(customer_id)

    if not customer:
        customer = find_customer_by_identifiers(phone=phone, pn_jid=pn_jid, lid_jid=lid_jid)

    if not customer:
        return jsonify({'status': 'unresolved', 'message': 'Customer not found'}), 200

    mapping_updated = persist_customer_mapping(
        customer,
        phone=phone or customer.phone,
        pn_jid=pn_jid,
        lid_jid=lid_jid,
    )
    if mapping_updated:
        db.session.commit()

    return jsonify(
        {
            'status': 'ok',
            'mapping_updated': mapping_updated,
            'customer': {
                'id': customer.id,
                'phone': customer.phone,
                'wa_pn_jid': customer.wa_pn_jid,
                'wa_lid_jid': customer.wa_lid_jid,
                'wa_mapping_updated_at': (
                    customer.wa_mapping_updated_at.isoformat()
                    if customer.wa_mapping_updated_at
                    else None
                ),
            },
        }
    ), 200


@system_bp.route('/api/stream')
def sse_stream():
    return stream_response()


@system_bp.route('/api/webhook', methods=['POST'])
def webhook():
    data = request.get_json(silent=True)
    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON body'}), 400

    print(f"Webhook received: {data}")

    try:
        if is_baileys_outgoing_event(data):
            response_payload, status_code = process_baileys_outgoing(data)
            return jsonify(response_payload), status_code

        if is_baileys_incoming_event(data):
            response_payload, status_code = process_baileys_incoming(data)
            return jsonify(response_payload), status_code

        if not ml_service.is_ready():
            return jsonify({'status': 'error', 'message': 'Model not loaded'}), 503

        _, response_payload, status_code = save_incoming_message(data)
        return jsonify(response_payload), status_code
    except Exception as exc:
        db.session.rollback()
        print(f"Error: {str(exc)}")
        return jsonify({'status': 'error', 'message': f'Internal server error: {str(exc)}'}), 500

@system_bp.route('/api/webhooktes', methods=['GET', 'POST'])
def webhook_test():
    if request.method == 'GET':
        return jsonify({
            'status': 'ready',
            'message': 'Gunakan POST untuk mengirim payload webhook test',
            'example_url': '/api/webhooktes',
        }), 200

    data = request.get_json(silent=True)

    if not data:
        return jsonify({'status': 'error', 'message': 'No JSON body'}), 400

    print(f"Webhook test received: {data}")

    payload = data.get('data') or {}
    key = payload.get('key') or {}

    remote_jid = key.get('remoteJid')
    from_me = key.get('fromMe', False)
    event = data.get('event')
    message_text = extract_wa_message_text(payload)

    normalized_phone = normalize_phone(remote_jid) if remote_jid else None
    normalized_pn_jid = normalize_jid(remote_jid) if remote_jid and remote_jid.endswith('@s.whatsapp.net') else None
    normalized_lid_jid = normalize_jid(remote_jid) if remote_jid and remote_jid.endswith('@lid') else None

    is_outgoing_from_me = bool(from_me) or event in [
        'message:out:new',
        'message:out:update',
        'message:out:ack',
    ]

    is_incoming_from_customer = not is_outgoing_from_me

    direction = 'outgoing_from_me' if is_outgoing_from_me else 'incoming_from_customer'

    resolved = data.get('resolved') or {}
    customer = find_customer_by_identifiers(
        phone=resolved.get('phone') or normalized_phone,
        pn_jid=resolved.get('wa_pn_jid') or resolved.get('pn_jid') or normalized_pn_jid,
        lid_jid=resolved.get('wa_lid_jid') or resolved.get('lid_jid') or normalized_lid_jid,
    )
    ticket_state = None
    eligible_for_auto_close = False
    mapping_updated = False
    mapping_snapshot = {
        'resolved_phone': resolved.get('phone'),
        'wa_pn_jid': resolved.get('wa_pn_jid') or resolved.get('pn_jid'),
        'wa_lid_jid': resolved.get('wa_lid_jid') or resolved.get('lid_jid'),
    }

    if customer:
        mapping_updated = persist_customer_mapping(
            customer,
            phone=mapping_snapshot['resolved_phone'] or customer.phone,
            pn_jid=mapping_snapshot['wa_pn_jid'] or normalized_pn_jid,
            lid_jid=mapping_snapshot['wa_lid_jid'] or normalized_lid_jid,
        )
        if mapping_updated:
            db.session.commit()
        ticket_state = build_customer_ticket_state(customer)
        eligible_for_auto_close = (
            is_outgoing_from_me and ticket_state['group_label'] == 'urgent'
        )

    return jsonify({
        'status': 'ok',
        'received_at': datetime.now().isoformat(),
        'parsed': {
            'event': event,
            'direction': direction,
            'is_chat_from_me': is_outgoing_from_me,
            'is_chat_from_customer': is_incoming_from_customer,
            'remote_jid': remote_jid,
            'normalized_phone': normalized_phone,
            'from_me': from_me,
            'message_text': message_text,
            'message_status': payload.get('status'),
            'message_id': key.get('id'),
            'top_level_keys': sorted(list(data.keys())),
            'payload_keys': sorted(list(payload.keys())) if payload else [],
            'key_keys': sorted(list(key.keys())) if key else [],
        },
        'customer_match': {
            'matched': bool(customer),
            'customer': (
                {
                    'id': customer.id,
                    'name': customer.name,
                    'phone': customer.phone,
                    'wa_pn_jid': customer.wa_pn_jid,
                    'wa_lid_jid': customer.wa_lid_jid,
                }
                if customer
                else None
            ),
        },
        'mapping': {
            'resolved': mapping_snapshot,
            'mapping_updated': mapping_updated,
            'remote_jid_kind': (
                'lid' if normalized_lid_jid else 'pn' if normalized_pn_jid else 'unknown'
            ),
        },
        'ticket_state': {
            'active_message_count': ticket_state['active_message_count'] if ticket_state else 0,
            'group_label': ticket_state['group_label'] if ticket_state else None,
            'active_intent_counts': (
                ticket_state['active_intent_counts']
                if ticket_state
                else {'urgent': 0, 'normal': 0, 'non_urgent': 0}
            ),
            'active_messages': [
                {
                    'id': msg.id,
                    'intent': msg.intent,
                    'status': msg.status,
                    'message_text': msg.message_text,
                    'timestamp': msg.timestamp.isoformat(),
                }
                for msg in (ticket_state['active_messages'] if ticket_state else [])
            ],
        },
        'decision': {
            'eligible_for_auto_close': eligible_for_auto_close,
            'auto_close_rule': 'outgoing only + group label must be urgent',
        },
        'raw': data,
    }), 200

@system_bp.route('/health')
def health():
    try:
        db.session.execute(db.text('SELECT 1'))
        db_status = 'connected'
    except Exception as exc:
        db_status = f'error: {str(exc)}'

    return jsonify(
        {
            'status': 'ok',
            'model_loaded': ml_service.is_ready(),
            'database': db_status,
            'sse_listeners': listener_count(),
        }
    ), 200


@system_bp.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json', mimetype='application/json')
