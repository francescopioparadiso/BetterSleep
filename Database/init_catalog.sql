-- USERS
create table users (
  id integer generated always as identity primary key,
  email text not null,
  password text not null,
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
  role text default 'owner'
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
  name text,
  bedtime time,
  wake_time time,
  desired_temperature integer,
  created_at timestamp with time zone default now()
);

