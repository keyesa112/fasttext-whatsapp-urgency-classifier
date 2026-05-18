from datetime import datetime

from extensions import db


class User(db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(30), default='admin', index=True)
    is_active = db.Column(db.Boolean, default=True, index=True)
    created_at = db.Column(db.DateTime, default=datetime.now)


class Customer(db.Model):
    __tablename__ = 'customers'

    id = db.Column(db.Integer, primary_key=True)
    phone = db.Column(db.String(20), unique=True, nullable=False, index=True)
    name = db.Column(db.String(100))
    wa_pn_jid = db.Column(db.String(60), nullable=True, index=True)
    wa_lid_jid = db.Column(db.String(60), nullable=True, index=True)
    wa_mapping_updated_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    messages = db.relationship(
        'Message',
        backref='customer',
        lazy=True,
        cascade='all, delete-orphan',
    )


class Message(db.Model):
    __tablename__ = 'messages'

    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(
        db.Integer,
        db.ForeignKey('customers.id', ondelete='CASCADE'),
        nullable=False,
    )
    message_text = db.Column(db.Text, nullable=False)
    intent = db.Column(db.String(20), index=True)
    confidence = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, nullable=False)
    is_handled = db.Column(db.Boolean, default=False)
    status = db.Column(db.String(20), default='pending', index=True)
    notified = db.Column(db.Boolean, default=False, index=True)
    last_notified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.now)

    __table_args__ = (
        db.Index('idx_intent_handled', 'intent', 'is_handled'),
        db.Index('idx_customer_timestamp', 'customer_id', 'timestamp'),
        db.Index('idx_customer_last_notified', 'customer_id', 'last_notified_at'),
    )
