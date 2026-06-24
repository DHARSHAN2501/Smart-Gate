import smtplib
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

sender_email = "preetiking143@gmail.com"
sender_password = "qbmg gucd qrlx rzsn"
receiver_email = "sivasakthi.s.2026@rkmshome.org"

sender_name = "ESP32 Sensor System"

subject = "ESP32 Sensor Data"

body = """
Sensor Monitoring Report

Temperature: 2 °C
Humidity: 86 %
Relay Status: OFF
"""

try:

    msg = MIMEMultipart()
    msg["From"] = f"{sender_name} <{sender_email}>"
    msg["To"] = receiver_email
    msg["Subject"] = subject

    msg.attach(MIMEText(body, "plain"))

    server = smtplib.SMTP("smtp.gmail.com", 587, timeout=20)

    server.starttls()

    server.login(sender_email, sender_password)

    server.sendmail(sender_email, receiver_email, msg.as_string())

    print("Email sent successfully")

    server.quit()

except (smtplib.SMTPException, socket.error) as e:
    print("Email failed:", e)