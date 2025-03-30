import requests
import time
from datetime import datetime, timedelta
import re

def get_unread_emails(api_key, base_url, log_function):
    all_emails = []
    unique_email_ids = set()
    offset = 0
    emails_per_page = 50  # Numero di email per richiesta
    max_retries = 5
    initial_retry_delay = 5
    start_time = time.time()
    max_runtime = 3600  # 1 ora di runtime massimo
    last_email_date = None

    while True:
        if time.time() - start_time > max_runtime:
            log_function("Raggiunto il tempo massimo di esecuzione. Terminazione della ricerca.")
            break

        try:
            url = f"{base_url}/emails"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            params = {
                "limit": emails_per_page,
                "offset": offset,
                "sort_order": "desc",
                "is_unread": "true",
                "include_lead_data": "true"
            }
            if last_email_date:
                params["created_before"] = last_email_date

            log_function(f"Richiesta API: URL={url}, Params={params}")
            response = make_request_with_backoff(url, headers, params, max_retries, initial_retry_delay, log_function)
            if response is None:
                log_function("Impossibile ottenere una risposta valida dopo multipli tentativi. Terminazione della ricerca.")
                break

            log_function(f"Risposta API: Status={response.status_code}, Content={response.text[:500]}...")
            data = response.json()
            emails = data.get('items', [])
            log_function(f"Email ricevute (offset {offset}): {len(emails)}")

            if not emails:
                log_function("Nessuna nuova email non letta trovata. Terminazione della ricerca.")
                break

            new_emails_count = 0
            for email in emails:
                if email['id'] not in unique_email_ids:
                    unique_email_ids.add(email['id'])
                    all_emails.append(email)
                    new_emails_count += 1
                    if last_email_date is None or email['timestamp_created'] < last_email_date:
                        last_email_date = email['timestamp_created']

            log_function(f"Nuove email non lette uniche trovate in questo batch: {new_emails_count}")
            log_function(f"Totale email non lette uniche trovate finora: {len(all_emails)}")
            if last_email_date:
                log_function(f"Data dell'ultima email recuperata: {last_email_date}")

            if len(emails) < emails_per_page:
                log_function("Raggiunte tutte le email non lette. Terminazione della ricerca.")
                break

            offset += emails_per_page
            time.sleep(1)
        except Exception as e:
            log_function(f"Errore durante il recupero delle email: {str(e)}")
            if 'response' in locals():
                log_function(f"Risposta completa: {response.text}")
            time.sleep(10)
            continue

    log_function(f"Totale email non lette uniche trovate: {len(all_emails)}")
    return all_emails

def make_request_with_backoff(url, headers, params, max_retries, initial_retry_delay, log_function):
    for attempt in range(max_retries):
        try:
            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            return response
        except (requests.RequestException, requests.Timeout) as e:
            wait_time = initial_retry_delay * (2 ** attempt)
            log_function(f"Tentativo {attempt + 1} fallito. Riprovo tra {wait_time} secondi... Errore: {str(e)}")
            time.sleep(wait_time)
    log_function("Tutti i tentativi di richiesta sono falliti.")
    return None

def classify_email(email, log_function):
    """
    Classifica l'email come 'interested' o 'non_interested' in base a:
      - Pattern regex negativi per espressioni di disinteresse
      - Parole chiave positive per interesse
      - Dati strutturati (lead_data)
    """
    content = (email.get('subject', '') + " " + email.get('content_preview', '')).lower()

    negative_patterns = [
        r"\bnon\s+(?:(?:sono|siamo|mi|abbiamo|ha|ho)\s+)?interess\w*\b",
        r"\bno,?\s+grazie\b",
        r"\bnon\s+lo\s+valutiamo\b",
        r"\bnon\s+è\s+per\s+noi\b",
        r"\bnon\s+fa\s+per\s+noi\b"
    ]
    for pattern in negative_patterns:
        if re.search(pattern, content):
            log_function(f"Email classified as non_interested due to negative pattern: {pattern}")
            return "non_interested"

    positive_keywords = [
        "interessato", "interessata", "interessati", "interessate", "interesse",
        "mi interessa", "sono interessato", "sono interessata",
        "mi interessa approfondire", "mi piacerebbe saperne di più",
        "fissiamo una call", "contattami", "contattatemi", "sono disponibile",
        "ok, mi interessa", "perfetto, parliamone", "vorrei fissare un appuntamento"
    ]
    for pos in positive_keywords:
        if pos in content:
            log_function(f"Email classified as interested due to keyword: {pos}")
            return "interested"

    lead_data = email.get('lead_data', {})
    status = lead_data.get('status', '').strip().lower()
    interest_status = lead_data.get('interest_status', '').strip().lower()
    labels = [str(label).strip().lower() for label in lead_data.get('labels', [])]
    note = lead_data.get('note', '').strip().lower()

    if status in ["interested", "interesse", "interessato", "interessata"]:
        log_function("Email classified as interested from structured data (status).")
        return "interested"
    if interest_status in ["interested", "interesse", "interessato", "interessata"]:
        log_function("Email classified as interested from structured data (interest_status).")
        return "interested"
    if any("interess" in label for label in labels):
        log_function("Email classified as interested from structured data (labels).")
        return "interested"
    if note and any(term in note for term in ["interessato", "interessata", "interesse", "interested"]):
        log_function("Email classified as interested from structured data (note).")
        return "interested"

    log_function("Email does not show clear interest. Classified as non_interested by default.")
    return "non_interested"
