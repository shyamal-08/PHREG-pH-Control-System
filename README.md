# PHREG – Automated pH Regulation System

## Overview
This project implements an embedded control system for automated pH regulation in CO₂-aerated microalgae cultures.

The system retrofits legacy Crison transmitters and integrates Mass Flow Controllers (MFC) to maintain stable pH using feedback control.

---

## Key Features
- Real-time pH monitoring via Crison MM44 transmitters
- CO₂ flow regulation using Mass Flow Controllers (MFC)
- PID-based control algorithm with safety constraints
- Modbus RTU communication (RS232)
- Data logging and dashboard interface
- Multi-reactor support

---

## System Architecture
![System Architecture](docs/architecture.png)

---

## Project Structure
controller/
├── main.py # Entry point
├── controller.py # Control loop logic
├── pid.py # PID controller
├── mfc.py # MFC communication
├── mm44.py # Sensor parsing
├── dashboard_io.py # Dashboard interface
├── logging_utils.py # Logging system
├── config.py # Configuration
└── utils.py # Helper functions


---

## How to Run

bash
pip install -r requirements.txt
python -m controller.main

## Results
Stable pH regulation achieved
Real-time monitoring and logging implemented
Modular embedded software architecture

## Technologies Used
Python
Modbus RTU (RS232)
Raspberry Pi
PID Control

## Authors
Shyamal Hirapara – Embedded Control System, Communication, Integration
Maulik – Dashboard, Data Logging, Visualization
