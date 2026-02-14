-- ==========================================
-- 1. CLEANUP
-- ==========================================
DROP TABLE IF EXISTS devices_services_details CASCADE;
DROP TABLE IF EXISTS devices CASCADE;
DROP TABLE IF EXISTS bedrooms CASCADE;
DROP TABLE IF EXISTS users CASCADE;
DROP TABLE IF EXISTS services CASCADE;
DROP TABLE IF EXISTS project_config CASCADE;

-- ==========================================
-- 2. CONFIGURAZIONE FUSO ORARIO (SINTASSI CORRETTA)
-- ==========================================
-- Imposta il timezone per il database corrente
-- Imposta il fuso orario per l'intero database
ALTER DATABASE bettersleep_catalog SET timezone TO 'Europe/Rome';

-- Forza il fuso orario per la sessione corrente
SET timezone = 'Europe/Rome';

-- ==========================================
-- 3. SCHEMA DEFINITION
-- ==========================================

CREATE TABLE services (
    service_id INT PRIMARY KEY,
    name TEXT,
    endpoint VARCHAR(255),
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE users (
    user_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    telegram_chat_id BIGINT
);

CREATE TABLE bedrooms (
    bedroom_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    user_id INT REFERENCES users(user_id) ON DELETE CASCADE,
    room_name VARCHAR(100) DEFAULT 'Bedroom'
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