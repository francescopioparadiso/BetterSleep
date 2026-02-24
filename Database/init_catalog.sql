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
    Bedtime TIME NOT NULL,
    Wakeup TIME NOT NULL,
    Desired_Temperature FLOAT NOT NULL
     );

CREATE TABLE users (
    telegram_chat_id BIGINT PRIMARY KEY ,
    username VARCHAR(100) UNIQUE NOT NULL,
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE SET NULL
);

CREATE TABLE devices (
    device_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    device_name VARCHAR(100),
    device_type VARCHAR(50),
    value INT NOT NULL ,
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE CASCADE
);

CREATE TABLE sensor(
    sensor_id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sensor_name VARCHAR(100),
    sensor_type VARCHAR(50),
    value FLOAT NOT NULL,
    bedroom_id INT REFERENCES bedrooms(bedroom_id) ON DELETE CASCADE
);