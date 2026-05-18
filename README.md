# WhatsApp Urgency Classification using FastText

A FastText-based text classification system for categorizing WhatsApp customer service messages into **urgent**, **normal**, and **non-urgent** classes.  
The system is designed to help pharmacy staff prioritize incoming customer messages through real-time classification, queue monitoring, and urgent message notification.

## Features

- WhatsApp message urgency classification using FastText
- Text preprocessing and supervised model training
- Flask REST API for real-time prediction
- WhatsApp Gateway webhook integration
- Queue-based monitoring dashboard
- Urgent message notification
- Ticket status tracking
- Model evaluation using accuracy, precision, recall, F1-score, and confusion matrix

## Tech Stack

- Python
- FastText
- Flask
- MySQL
- SQLAlchemy
- JavaScript
- Tailwind CSS
- WhatsApp Gateway
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
