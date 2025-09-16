from flask import Flask, request, jsonify
import requests
import time
import threading
import qrcode
import base64
from io import BytesIO
import os
import redis
from flask_cors import CORS
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# ====== Redis setup ======
redis_url = os.environ.get("REDIS_URL")
r = redis.from_url(redis_url, decode_responses=True)

app = Flask(__name__)
CORS(app, origins=["https://mr-xneuro.github.io"])

# ====== Config ======
RECEIVING_ADDRESS = "ltc1q8lhjswg03t8pkw62ht59pq8za7wn2xvqmxcsxk"
EXPECTED_AMOUNT = 3.6  # LTC
ADMIN_EMAIL = "mrxai-architect@tuta.io"
SUPPORT_EMAIL = "wilicower@gmail.com"
BLOCKCYPHER_TOKEN = "4a658c640789481bb34b31e1a4a13338"
CHECK_INTERVAL = 90  # seconds

SMTP_SERVER = "smtp.mailersend.net"
SMTP_PORT = 587
SMTP_USER = "MS_oYfPbt@test-zxk54v8r551ljy6v.mlsender.net"
SMTP_PASS = "mssp.JhhShYw.vywj2lp0nxp47oqz.jhqxPhV"

orders = []

# ====== Background: Payment Check ======
def check_payments():
    while True:
        for order in orders:
            if order['confirmed']:
                continue

            url = f"https://api.blockcypher.com/v1/ltc/main/addrs/{RECEIVING_ADDRESS}/full?token={BLOCKCYPHER_TOKEN}"
            try:
                response = requests.get(url)
                if response.status_code != 200:
                    print(f"[!] Failed to get txs: {response.text}")
                    continue

                data = response.json()
                txs = data.get("txs", [])

                for tx in txs:
                    for output in tx.get("outputs", []):
                        if RECEIVING_ADDRESS in output.get("addresses", []):
                            value_received = output.get("value", 0) / 1e8
                            confirmations = tx.get("confirmations", 0)
                            if value_received >= EXPECTED_AMOUNT and confirmations >= 1:
                                if not order['confirmed']:
                                    order['confirmed'] = True
                                    order['txid'] = tx.get("hash")

                                    ref_code = order.get("ref")
                                    if ref_code:
                                        r.hincrby(f"affiliate:{ref_code}", "sales", 1)
                                        r.rpush(f"affiliate:{ref_code}:txs", tx.get("hash"))

                                    send_emails(order)
            except Exception as e:
                print(f"[!] Error checking payment: {e}")

        time.sleep(CHECK_INTERVAL)

# ====== Email sender ======
def send_emails(order):
    user_email = order['email']
    txid = order['txid']
    payment_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())

    # To user
    msg_user = MIMEMultipart()
    msg_user["From"] = SMTP_USER
    msg_user["To"] = user_email
    msg_user["Subject"] = "✅ Payment Confirmed - NeuroBet"

    body_user = f"""
    <html><body>
    <p>Dear user,</p>
    <p>Your Litecoin payment was successfully received.</p>
    <p><b>TXID:</b> {txid}</p>
    <p>We will email your licensed software within the next few hours.</p>
    <p>Thank you for choosing NeuroBet!</p>
    </body></html>
    """
    msg_user.attach(MIMEText(body_user, "html"))

    # To admin
    msg_admin = MIMEMultipart()
    msg_admin["From"] = SMTP_USER
    msg_admin["To"] = SUPPORT_EMAIL
    msg_admin["Subject"] = "🟢 New Payment Received - NeuroBet"

    body_admin = f"""
    <html><body>
    <p>A new payment has been received:</p>
    <ul>
      <li><b>User Email:</b> {user_email}</li>
      <li><b>TXID:</b> {txid}</li>
      <li><b>Received At:</b> {payment_time}</li>
    </ul>
    <p>Please prepare license and delivery package.</p>
    </body></html>
    """
    msg_admin.attach(MIMEText(body_admin, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg_user)
            server.send_message(msg_admin)
            print("[✓] Emails sent to user and support.")
    except Exception as e:
        print(f"[!] Failed to send emails: {e}")

# ====== Order API ======
@app.route("/order", methods=['POST'])
def receive_order():
    data = request.json
    email = data.get('email')
    if not email:
        return jsonify({"error": "Email is required"}), 400

    ref_code = data.get("ref")
    if ref_code:
        key = f"affiliate:{ref_code}"
        if not r.exists(key):
            r.hset(key, mapping={"clicks": 1, "sales": 0})
        else:
            r.hincrby(key, "clicks", 1)

    new_order = {
        "email": email,
        "timestamp": time.time(),
        "confirmed": False,
        "txid": None,
        "ref": ref_code
    }
    orders.append(new_order)

    payment_uri = f"litecoin:{RECEIVING_ADDRESS}?amount={EXPECTED_AMOUNT}"
    qr = qrcode.make(payment_uri)
    buffer = BytesIO()
    qr.save(buffer, format="PNG")
    qr_base64 = base64.b64encode(buffer.getvalue()).decode()

    return jsonify({
        "message": "Order received",
        "address": RECEIVING_ADDRESS,
        "amount_ltc": EXPECTED_AMOUNT,
        "qr": f"data:image/png;base64,{qr_base64}"
    })

# ====== Affiliate Dashboard HTML ======
@app.route("/affiliate-dashboard")
def affiliate_dashboard_html():
    ref = request.args.get("ref")
    if not ref:
        return "<h3>Missing referral code (?ref=...)</h3>", 400

    key = f"affiliate:{ref}"
    if not r.exists(key):
        return f"<h3>No data found for {ref}</h3>", 404

    clicks = r.hget(key, "clicks") or "0"
    sales = r.hget(key, "sales") or "0"
    txs = r.lrange(f"{key}:txs", 0, -1)
    earnings = round(float(sales) * 0.035, 5)

    tx_html = "<ul>" + "".join([f"<li>{txid}</li>" for txid in txs]) + "</ul>" if txs else "<p>No transactions yet.</p>"

    html = f"""
    <html>
        <head><title>Affiliate Dashboard - {ref}</title></head>
        <body style='font-family:sans-serif;max-width:600px;margin:auto;padding:20px'>
            <h2>📊 Affiliate Dashboard</h2>
            <p><strong>Email:</strong> {ref}</p>
            <p><strong>Total Clicks:</strong> {clicks}</p>
            <p><strong>Total Sales:</strong> {sales}</p>
            <p><strong>Estimated Earnings:</strong> {earnings} LTC</p>
            <h3>Transactions:</h3>
            {tx_html}
        </body>
    </html>
    """
    return html

# ====== Home ======
@app.route("/")
def home():
    return "NeuroBet Litecoin backend is running with BlockCypher."

# ====== Background Thread ======
th = threading.Thread(target=check_payments)
th.daemon = True
th.start()

# ====== Run Server ======
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)

