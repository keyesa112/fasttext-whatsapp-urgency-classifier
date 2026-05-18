CREATE DATABASE IF NOT EXISTS apotek_k24_whatsapp
CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE apotek_k24_whatsapp;

SET SQL_SAFE_UPDATES = 0;

-- ==============================================
-- CUSTOMERS TABLE
-- ==============================================
CREATE TABLE customers (
    id INT AUTO_INCREMENT PRIMARY KEY,
    phone VARCHAR(20) UNIQUE NOT NULL,
    name VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    INDEX idx_phone (phone)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- MESSAGES TABLE (FULL FEATURES)
-- ==============================================
CREATE TABLE messages (
    id INT AUTO_INCREMENT PRIMARY KEY,
    
    -- Customer reference
    customer_id INT NOT NULL,
    
    -- WhatsApp message
    message_text TEXT NOT NULL,
    
    -- AI Classification
    intent VARCHAR(20),
    confidence FLOAT,
    
    -- Timestamp
    timestamp DATETIME NOT NULL,
    
    -- Status tracking
    is_handled BOOLEAN DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    
    -- Notification tracking
    notified BOOLEAN DEFAULT 0,
    last_notified_at DATETIME NULL,
    
    -- Audit
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    
    -- FOREIGN KEY
    FOREIGN KEY (customer_id) REFERENCES customers(id) ON DELETE CASCADE,
    
    -- OPTIMIZATION INDEXES
    INDEX idx_intent_handled (intent, is_handled),
    INDEX idx_customer_timestamp (customer_id, timestamp),
    INDEX idx_notified (notified),
    INDEX idx_status (status),
    INDEX idx_customer_last_notified (customer_id, last_notified_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ==============================================
-- VERIFY TABLES
-- ==============================================
SHOW TABLES;
DESCRIBE customers;
DESCRIBE messages;

-- ==============================================
-- SAMPLE DATA (Optional - untuk testing)
-- ==============================================
INSERT INTO customers (phone, name) VALUES 
('6281234567890', 'Test Customer 1'),
('6289876543210', 'Test Customer 2'),
('6285551234567', 'Budi Santoso'),
('6287778889990', 'Siti Aminah');

INSERT INTO messages (customer_id, message_text, intent, confidence, timestamp, status) VALUES
(1, 'Kak, buku biografi butuh sekarang', 'urgent', 0.95, '2026-02-24 18:00:00', 'pending'),
(1, 'Kak, stok buku biografi berapa?', 'normal', 0.87, '2026-02-24 18:01:00', 'pending'),
(2, 'Mau beli buku novel', 'non_urgent', 0.92, '2026-02-24 17:45:00', 'in_progress'),
(3, 'Kak, novel terbaru ada?', 'normal', 0.88, '2026-02-24 17:30:00', 'completed'),
(4, 'Pesan buku anak', 'non_urgent', 0.91, '2026-02-24 17:00:00', 'pending');

SELECT * FROM customers;
SELECT * FROM messages ORDER BY timestamp DESC;
