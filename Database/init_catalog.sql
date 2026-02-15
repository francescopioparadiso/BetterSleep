-- ==========================================
-- 3. SCHEMA DEFINITION (MODIFICATO)
-- ==========================================

CREATE TABLE services (
    service_id INT PRIMARY KEY,
    name TEXT,
    endpoint VARCHAR(255),
    type VARCHAR(20),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Spostiamo bedrooms SOPRA users perché users ora ne dipende
CREATE TABLE bedrooms (
    bedroom_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    room_name VARCHAR(100) DEFAULT 'Bedroom',
    password VARCHAR(255) NOT NULL
);

CREATE TABLE users (
    telegram_chat_id BIGINT PRIMARY KEY ,
    username VARCHAR(100) UNIQUE NOT NULL,
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE SET NULL
);

CREATE TABLE devices (
    device_id VARCHAR(100) PRIMARY KEY,
    device_name VARCHAR(100),
    measure_types TEXT[],
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE SET NULL,
    last_update TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE devices_services_details (
    id SERIAL PRIMARY KEY,
    device_id VARCHAR(100) REFERENCES devices(device_id) ON DELETE CASCADE,
    service_type VARCHAR(20),
    service_ip VARCHAR(100),
    mqtt_topics TEXT[]
);