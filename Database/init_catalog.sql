-- ==========================================
-- 1. CLEANUP (Optional: Drops tables to start fresh)
-- ==========================================
DROP TABLE IF EXISTS device_services CASCADE;
DROP TABLE IF EXISTS devices CASCADE;
DROP TABLE IF EXISTS bedrooms CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS project_config CASCADE;

-- ==========================================
-- 2. SCHEMA DEFINITION
-- ==========================================

-- Table for the "servicesList" (Microservices in the architecture)
CREATE TABLE services (
    service_id VARCHAR(100) PRIMARY KEY,
    description TEXT,
    rest_endpoint VARCHAR(255),
    mqtt_topic VARCHAR(255),
    token VARCHAR(255),
    timestamp TIMESTAMP
);

-- Tabella utenti
CREATE TABLE users (
    user_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,  -- Auto-generato
    username VARCHAR(100) UNIQUE NOT NULL,                -- Nome unico
    telegram_chat_id BIGINT
);

CREATE TABLE bedrooms (
    bedroom_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    room_name VARCHAR(100) DEFAULT 'Bedroom'
);



-- Table for "devicesList"
CREATE TABLE devices (
    device_id INT PRIMARY KEY,
    device_name VARCHAR(100),
    measure_types TEXT[], -- Postgres Array to store ["Temperature", "Humidity"]
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE SET NULL, -- Link to room
    last_update TIMESTAMP
);

-- Table for "service-sDetails" (How to connect to the device)
CREATE TABLE devices_services_details (
    id SERIAL PRIMARY KEY,
    device_id INT REFERENCES devices(device_id) ON DELETE CASCADE,
    service_type VARCHAR(20), -- 'MQTT' or 'REST'
    service_ip VARCHAR(100),  -- For REST
    mqtt_topics TEXT[]        -- For MQTT (Array of strings)
);

