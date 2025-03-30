from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
import os
import requests
from openai import OpenAI
from dotenv import load_dotenv
from email_processor import get_unread_emails, classify_email

# Crea l'istanza FastAPI
app = FastAPI()

# Carica variabili da .env
load_dotenv()

# Configurazioni API
INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
INSTANTLY_BASE_URL = os.getenv("INSTANTLY_BASE_URL")

client = OpenAI(api_key=OPENAI_API_KEY)

# ----------- MODELLI -----------
class EmailData(BaseModel):
    id: str
    subject: str = ""
    body: str = ""
    from_address_email: str
    to_address_email_list: list[str] | str = []
    thread_id: str = ""

class GenerateRequest(BaseModel):
    content: str

class SendRequest(BaseModel):
    email: EmailData
    response: str

# ----------- ENDPOINTS -----------
@app.get("/")
def root():
    return {"status": "API attiva"}

@app.get("/check-emails")
def check_emails():
    def dummy_log(msg):
        print(msg)

    unread = get_unread_emails(INSTANTLY_API_KEY, INSTANTLY_BASE_URL, dummy_log)
    interested, not_interested = [], []
    for email in unread:
        classification = classify_email(email, dummy_log)
        if classification == "interested":
            interested.append(email)
        else:
            not_interested.append(email)

    return {
        "interested": interested,
        "not_interested": not_interested,
        "total": len(unread)
    }

@app.post("/generate-response")
def generate_ai_response(data: GenerateRequest):
    try:
        thread = client.beta.threads.create()
        client.beta.threads.messages.create(
            thread_id=thread.id,
            role="user",
            content=f"Please generate a response to this email: {data.content}"
        )
        run = client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=ASSISTANT_ID
        )
        while run.status != "completed":
            run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
        messages = client.beta.threads.messages.list(thread_id=thread.id)
        for message in messages:
            if message.role == "assistant":
                return {"response": message.content[0].text.value}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/send-response")
def send_email(data: SendRequest):
    email = data.email
    response_text = data.response

    if isinstance(email.to_address_email_list, list):
        from_value = email.to_address_email_list[0] if email.to_address_email_list else ""
    else:
        from_value = email.to_address_email_list.split(",")[0]

    prepared_response = response_text.replace("\n", "<br>")

    payload = {
        "reply_to_uuid": email.id,
        "subject": f"Re: {email.subject}",
        "from": from_value,
        "to": email.from_address_email,
        "body": {"text": prepared_response},
        "eaccount": from_value
    }
    if email.thread_id:
        payload["reminder_ts"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

    headers = {
        "Authorization": f"Bearer {INSTANTLY_API_KEY}",
        "Content-Type": "application/json"
    }
    try:
        url = f"{INSTANTLY_BASE_URL}/emails/reply"
        res = requests.post(url, headers=headers, json=payload)
        res.raise_for_status()
        return {"status": "success", "response": res.json()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
