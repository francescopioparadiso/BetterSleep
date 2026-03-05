-- USERS
create table users (
  id integer generated always as identity primary key,
  email text UNIQUE not null,
  password text not null,
  night_time text default '22:00',
  morning_time text default '07:00',
  created_at timestamp with time zone default now()
);

-- HOUSES
create table houses (
  id integer generated always as identity primary key,
  name text not null,
  created_at timestamp with time zone default now()
);

-- HOUSE MEMBERS
create table house_members (
  id integer generated always as identity primary key,
  house_id integer references houses(id) on delete cascade,
  user_id integer references users(id) on delete cascade,
  role integer default 0 -- 0: admin, 1: member (VIRGOLA RIMOSSA QUI!)
);

-- INVITATIONS
create table invitations (
  id integer generated always as identity primary key,
  house_id integer references houses(id) on delete cascade,
  email text,
  status integer default 0, -- 0: pending, 1: accepted, 2: rejected
  created_at timestamp with time zone default now()
);

-- ROOMS
create table rooms (
  id integer generated always as identity primary key,
  house_id integer references houses(id) on delete cascade,
  user_id integer references users(id) on delete cascade,
  name text,
  created_at timestamp with time zone default now(),
  temperature_night integer default 18,
  temperature_morning integer default 22,
  light_night integer default 0,
  light_morning integer default 100
);

-- SENSORS
create table sensors (
  id integer generated always as identity primary key,
  room_id integer references rooms(id) on delete cascade,
  type text not null, -- ambient_temp, humidity, light, heart_rate, vibration, presence
  name text not null,
  mqtt_topic text,
  created_at timestamp with time zone default now()
);