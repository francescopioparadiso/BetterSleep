<p align="left">
  <img src="/README/bettersleep.png" alt="BetterSleep logo" height="50">
  &nbsp;&nbsp;&nbsp;
  &nbsp;&nbsp;&nbsp;
  <img src="/README/polito.png" alt="Politecnico di Torino logo" height="50">
</p>

<h1 align="left">BetterSleep</h1>

BetterSleep is a smart bedroom monitoring project that combines an iOS app, a set of backend microservices, and a sleep simulation environment. In a simple way, it helps connect bedroom sensors, backend analytics, and a mobile interface to monitor sleep conditions and test the whole platform end to end.

The project includes:

- an iOS app for users
- backend microservices for catalog, users, time-series data, analytics, and sleep-cycle management
- Dockerized infrastructure with PostgreSQL, MongoDB, and MQTT
- a simulation tool to generate realistic sleep-night data for testing

## How to run it

All the main workflows are already available as VS Code tasks.

Open the `Code` folder in VS Code, then go to:

`Terminal > Run Task...`

Use the following tasks.

## 1. Start all servers

Run:

`🚀 Start All Servers`

This task starts the full backend stack with Docker Compose, including:
- PostgreSQL
- MongoDB
- MQTT broker
- Catalog
- User Service
- Time Series
- Bed Analytics
- Sleep Cycle Manager

Make sure Docker Desktop is installed and running before launching this task.

## 2. QR code

Run:

`🖥️ Show Mac IP QR`

This task detects your Mac local IP address, generates a QR code, and opens it automatically.

This is useful when testing the BetterSleep app on a physical iPhone: scan the QR code from the app so it can connect to the backend running on your computer.

## 3. Simulation

Run:

`🧪 Test Sleep Cycle`

This task launches the interactive sleep simulation.

It will:
- fetch the active users
- let you choose which users to simulate
- ask for a target date
- ask for the sleep quality (`good`, `fair`, or `poor`)
- publish simulated sensor data to the platform

Before running the simulation, make sure the servers are already running.

## Suggested order

1. Run `🚀 Start All Servers`
2. Run `🖥️ Show Mac IP QR` if you are testing on a real device
3. Run `🧪 Test Sleep Cycle` to generate test data

## Notes

- Run the tasks from the `Code` workspace folder.
- The QR code is mainly needed for physical-device testing.
- The simulation is useful for testing charts, analytics, and platform behavior with realistic sleep data.
