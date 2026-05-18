# WhatsApp Urgency Classification using FastText

A FastText-based text classification system for categorizing WhatsApp customer service messages into **urgent**, **normal**, and **non-urgent** classes.  
The system is designed to help pharmacy staff prioritize incoming customer messages through real-time classification, queue monitoring, urgent message notification, and reply status tracking.

## Features

- WhatsApp message urgency classification using FastText
- Text preprocessing and supervised model training
- Flask REST API for real-time prediction
- WhatsApp Gateway webhook integration for incoming messages
- Baileys listener integration for detecting outgoing/manual replies
- Queue-based monitoring dashboard
- Urgent message notification
- Ticket grouping and status tracking
- Quick link access to WhatsApp conversations
- Real-time dashboard updates using Server-Sent Events
- Model evaluation using accuracy, precision, recall, F1-score, and confusion matrix

## Tech Stack

- Python
- FastText
- Flask
- MySQL
- SQLAlchemy
- JavaScript
- Tailwind CSS
- WhatsApp Gateway / Fonnte
- Baileys
- Server-Sent Events

## Model Performance

The best-performing model achieved:

- Accuracy: 79.21%
- Urgent class recall: 83%

## Project Structure

```text
.
├── app/
│   ├── api/
│   ├── models/
│   ├── templates/
│   └── static/
├── data/
├── notebooks/
├── model/
├── scripts/
├── requirements.txt
└── README.md
