import os
import json
import pandas as pd
from flask import Flask, request, jsonify
import requests

# --------------------------
# Load Excel file (ensure it's in your repo root!)
# --------------------------
EXCEL_FILE = "AEFI_Training_Sample.xlsx"
try:
    df = pd.read_excel(EXCEL_FILE)
except Exception as e:
    print(f"⚠️ Could not load Excel file: {e}")
    df = pd.DataFrame()  # fallback

# --------------------------
# Flask app
# --------------------------
app = Flask(__name__)

# WhatsApp API credentials
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")

# Session store (in-memory)
user_sessions = {}

# --------------------------
# Helper functions
# --------------------------
def send_whatsapp_message(to, message):
    """Send plain text message via WhatsApp API"""
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "text": {"body": message}
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    print("Send message response:", response.text)


def send_button_message(to, body_text, buttons):
    """Send button-based interactive message"""
    url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": buttons}
        }
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    print("Send button response:", response.text)


def send_start_prompt(to):
    """Ask user to start quiz"""
    send_button_message(
        to,
        "नमस्ते! AEFI प्रशिक्षण बॉट में आपका स्वागत है 🙏\nक्या आप क्विज़ शुरू करना चाहेंगे?",
        [
            {"type": "reply", "reply": {"id": "start_quiz", "title": "शुरू करें ✅"}}
        ]
    )


def send_question(to, q_index):
    """Send one question with its options"""
    if df.empty:
        send_whatsapp_message(to, "⚠️ प्रश्न डेटा उपलब्ध नहीं है।")
        return

    row = df.iloc[q_index]
    # FIX: safe access
    question_text = row["Question"] if "Question" in row and pd.notna(row["Question"]) else row[df.columns[0]]
    body_text = f"प्रश्न {q_index+1}: {question_text}"

    # Collect options
    options = []
    for i in range(1, 5):
        col = f"Option {i}"
        if col in row and pd.notna(row[col]):
            options.append((i, str(row[col])))

    print("📤 Question sent:", body_text)
    print("📤 Options:", [opt[1] for opt in options])

    # Case 1: If <= 3 options → send as buttons
    if len(options) <= 3:
        buttons = [
            {"type": "reply", "reply": {"id": str(i), "title": title[:20]}}
            for i, title in options
        ]
        send_button_message(to, body_text, buttons)

    # Case 2: If > 3 options → send as list (works for 4)
    else:
        url = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json"
        }
        data = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": "विकल्प चुनें",
                    "sections": [
                        {
                            "title": "उत्तर चुनें",
                            "rows": [
                                {"id": str(i), "title": title[:20]}
                                for i, title in options
                            ]
                        }
                    ]
                }
            }
        }
        response = requests.post(url, headers=headers, data=json.dumps(data))
        print("Send list response:", response.text)


# --------------------------
# Routes
# --------------------------

@app.route("/", methods=["GET"])
def home():
    return "✅ AEFI WhatsApp Bot is running!", 200


# Webhook Verification
@app.route("/webhook", methods=["GET"])
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        print("Webhook verified successfully ✅")
        return challenge, 200
    else:
        print("❌ Webhook verification failed")
        return "Verification failed", 403


# Webhook Receiver
@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json()
    print("RAW Incoming:", data)
    print("Incoming webhook:", json.dumps(data, indent=2, ensure_ascii=False))

    try:
        if "messages" in data.get("entry", [])[0].get("changes", [])[0]["value"]:
            message = data["entry"][0]["changes"][0]["value"]["messages"][0]
            from_number = message["from"]

            # Ensure session exists
            if from_number not in user_sessions:
                user_sessions[from_number] = {"score": 0, "q_index": None}

            # Handle text messages
            if message.get("type") == "text":
                if user_sessions[from_number]["q_index"] is None:
                    send_start_prompt(from_number)
                    return jsonify({"status": "ok"}), 200
            
            # Handle interactive replies
            if message.get("type") == "interactive":
                interactive_type = message["interactive"].get("type")
            
                button_id = None
                if interactive_type == "button_reply":
                    button_id = message["interactive"]["button_reply"]["id"]
                elif interactive_type == "list_reply":
                    button_id = message["interactive"]["list_reply"]["id"]
            
                if not button_id:
                    print("⚠️ Unknown interactive type:", interactive_type)
                    return jsonify({"status": "ignored"}), 200

                # Case 1: User pressed Start
                if button_id == "start_quiz":
                    user_sessions[from_number]["q_index"] = 0
                    print("📌 Sending first question...")
                    print("📌 DataFrame shape:", df.shape)
                    if df.empty:
                        send_whatsapp_message(from_number, "⚠️ कोई प्रश्न लोड नहीं हुआ। Excel फ़ाइल देखें।")
                    else:
                        send_question(from_number, 0)
                    return jsonify({"status": "ok"}), 200


                # Case 2: User answered a question
                session = user_sessions[from_number]
                q_index = session["q_index"]
                row = df.iloc[q_index]

               # Keep IDs as string (avoid int conversion)
                choice = str(button_id)
                correct_option = str(int(row["Correct Option"]))
                
                # Update score and send explanation
                if choice == correct_option:
                    session["score"] += 1
                    explanation = row.get(f"Explanation {choice}", "कोई विवरण उपलब्ध नहीं।")
                    send_whatsapp_message(
                        from_number,
                        f"✅ सही उत्तर!\n{explanation}"
                    )
                else:
                    correct_expl = row.get(f"Explanation {correct_option}", "कोई विवरण उपलब्ध नहीं।")
                    send_whatsapp_message(
                        from_number,
                        f"❌ गलत उत्तर।\n👉 सही उत्तर: {row[f'Option {correct_option}']}\nℹ️ कारण: {correct_expl}"
                    )


                # Next question or end
                session["q_index"] += 1
                if session["q_index"] < len(df):
                    send_question(from_number, session["q_index"])
                else:
                    send_whatsapp_message(
                        from_number,
                        f"🎉 प्रशिक्षण पूरा हुआ!\nआपका स्कोर: {session['score']}/{len(df)}"
                    )
                    del user_sessions[from_number]  # clear session

    except Exception as e:
        print("⚠️ Error processing webhook:", e)

    return jsonify({"status": "ok"}), 200


# --------------------------
# Run
# --------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)


