import sys
import os
import json
import requests
import time
from datetime import datetime

from openai import OpenAI
from email_processor import get_unread_emails, classify_email

# Load environment variables (opzionale, se ne usi alcune)
from dotenv import load_dotenv
load_dotenv()


# API keys and URL configuration (incorporate direttamente)
INSTANTLY_API_KEY = os.getenv("INSTANTLY_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ASSISTANT_ID = os.getenv("ASSISTANT_ID")
INSTANTLY_BASE_URL = os.getenv("INSTANTLY_BASE_URL")

# Initialize OpenAI client
client = OpenAI(api_key=OPENAI_API_KEY)

def prepare_text_for_sending(text):
    return text.replace('\n', '<br>')

# -----------------------------
# Funzione per salvare l'email nel Google Sheet
# -----------------------------
try:
    import gspread
    from google.oauth2.service_account import Credentials

    def salva_email_in_google_sheet(email, sheet_id, credenziali_file="ai-agent-450915-5a91975b504e.json"):
        """
        Apre il Google Sheet con il key fornito e aggiunge una riga contenente l'email e il timestamp.
        Se l'app è compilata con PyInstaller, utilizza sys._MEIPASS per il percorso.
        """
        if hasattr(sys, '_MEIPASS'):
            base_path = sys._MEIPASS
        else:
            base_path = os.path.abspath(".")
        credenziali_file_path = os.path.join(base_path, credenziali_file)
        scope = [
            'https://www.googleapis.com/auth/spreadsheets',
            'https://www.googleapis.com/auth/drive'
        ]
        creds = Credentials.from_service_account_file(credenziali_file_path, scopes=scope)
        client_gspread = gspread.authorize(creds)
        sheet = client_gspread.open_by_key(sheet_id).sheet1  # Modifica "sheet1" se necessario
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        sheet.append_row([email, timestamp])
except ModuleNotFoundError:
    print("Warning: gspread or google-auth is not installed. The salva_email_in_google_sheet function will not be operational.")
    def salva_email_in_google_sheet(email, sheet_id, credenziali_file):
        print("Dummy: Saving email to Google Sheet not executed.")

# -----------------------------
# Classe per il thread di controllo email
# -----------------------------
class EmailCheckerThread(QThread):
    update_progress = pyqtSignal(int)
    finished = pyqtSignal(list, int)
    log_message = pyqtSignal(str)

    def __init__(self, api_key, base_url, parent=None):
        super().__init__(parent)
        self.api_key = api_key
        self.base_url = base_url

    def run(self):
        unread_emails = get_unread_emails(self.api_key, self.base_url, self.log_message.emit)
        self.finished.emit(unread_emails, len(unread_emails))

# -----------------------------
# Classe principale MainWindow
# -----------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Email AI Responder")
        self.setGeometry(100, 100, 1600, 900)

        # Internal email queues
        self.interested_emails_queue = []
        self.non_interested_emails_queue = []
        self.current_email = None
        self.ai_original_response = ""  # Per salvare la risposta AI originale

        # Main widget and layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QHBoxLayout(main_widget)

        # Left area: email queues
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        self.interested_queue_label = QLabel("Lead interessati: 0")
        left_layout.addWidget(self.interested_queue_label)
        self.interested_queue_list = QListWidget()
        left_layout.addWidget(self.interested_queue_list)
        self.interested_queue_list.itemClicked.connect(self.email_selected_interested)

        self.non_interested_queue_label = QLabel("Lead non interessati: 0")
        left_layout.addWidget(self.non_interested_queue_label)
        self.non_interested_queue_list = QListWidget()
        left_layout.addWidget(self.non_interested_queue_list)
        self.non_interested_queue_list.itemClicked.connect(self.email_selected_non_interested)

        layout.addWidget(left_widget, 1)

        # Right area: log and response
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        layout.addWidget(right_widget, 3)

        # Splitter for log and response area
        splitter = QSplitter(Qt.Orientation.Vertical)
        right_layout.addWidget(splitter)

        # Log area
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        self.email_counter = QLabel("Email non lette uniche: 0")
        log_layout.addWidget(self.email_counter)
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        splitter.addWidget(log_widget)

        # Response area
        response_widget = QWidget()
        response_layout = QVBoxLayout(response_widget)

        self.current_email_label = QLabel("Email corrente: Nessuna")
        response_layout.addWidget(self.current_email_label)

        self.client_response_label = QLabel("Email del cliente:")
        response_layout.addWidget(self.client_response_label)
        self.client_response_text = QTextEdit()
        self.client_response_text.setReadOnly(True)
        response_layout.addWidget(self.client_response_text)

        self.ai_response_label = QLabel("Risposta AI:")
        response_layout.addWidget(self.ai_response_label)
        self.response_text = QTextEdit()
        response_layout.addWidget(self.response_text)

        # Control buttons arranged in two rows:
        button_layout = QVBoxLayout()
        button_row1 = QHBoxLayout()
        button_row2 = QHBoxLayout()

        # First row: [Genera Risposta] [Pianifica Promemoria] [Invia]
        self.btn_generate = QPushButton("Genera Risposta")
        self.btn_generate.clicked.connect(self.elabora_risposta_ai)
        button_row1.addWidget(self.btn_generate)

        self.btn_reminder = QPushButton("Pianifica Promemoria")
        self.btn_reminder.clicked.connect(self.set_reminder)
        button_row1.addWidget(self.btn_reminder)

        self.btn_send = QPushButton("Invia")
        self.btn_send.clicked.connect(self.send_response)
        button_row1.addWidget(self.btn_send)

        # Second row: [Marca come Letta] [Ignora] [Aggiorna]
        self.btn_mark = QPushButton("Marca come Letta")
        self.btn_mark.clicked.connect(self.mark_as_read)
        button_row2.addWidget(self.btn_mark)

        self.btn_ignore = QPushButton("Ignora")
        self.btn_ignore.clicked.connect(self.skip_email)
        button_row2.addWidget(self.btn_ignore)

        self.btn_refresh = QPushButton("Aggiorna")
        self.btn_refresh.clicked.connect(self.refresh_script)
        button_row2.addWidget(self.btn_refresh)

        button_layout.addLayout(button_row1)
        button_layout.addLayout(button_row2)
        response_layout.addLayout(button_layout)

        splitter.addWidget(response_widget)

        self.update_button_states(False)
        self.log("Avvio del sistema di monitoraggio email...")
        self.check_emails()

        # Assicura che la cartella per il salvataggio delle risposte esista
        if not os.path.exists('correzioni'):
            os.makedirs('correzioni')

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        self.log_text.verticalScrollBar().setValue(self.log_text.verticalScrollBar().maximum())

    def update_button_states(self, enabled=True):
        self.btn_generate.setEnabled(enabled)
        self.btn_send.setEnabled(enabled)
        self.btn_mark.setEnabled(enabled)
        self.btn_reminder.setEnabled(enabled)
        self.btn_ignore.setEnabled(enabled)

    def check_emails(self):
        self.log("Controllo nuove email in corso...")
        self.email_checker_thread = EmailCheckerThread(INSTANTLY_API_KEY, INSTANTLY_BASE_URL, self)
        self.email_checker_thread.finished.connect(self.handle_email_check_result)
        self.email_checker_thread.log_message.connect(self.log)
        self.email_checker_thread.start()

    def handle_email_check_result(self, unread_emails, unread_count):
        self.log(f"Totale email non lette uniche: {unread_count}")
        self.email_counter.setText(f"Email non lette uniche: {unread_count}")
        self.process_unread_emails(unread_emails)

    def process_unread_emails(self, unread_emails):
        self.log("Elaborazione delle email non lette...")
        self.interested_emails_queue = []
        self.non_interested_emails_queue = []
        self.interested_queue_list.clear()
        self.non_interested_queue_list.clear()

        for email in unread_emails:
            classification = classify_email(email, self.log)
            if classification == "interested":
                self.interested_emails_queue.append(email)
                self.log(f"Aggiunta alla coda interessati: {email.get('subject', 'No Subject')}")
            else:
                self.non_interested_emails_queue.append(email)
                self.log(f"Aggiunta alla coda non interessati: {email.get('subject', 'No Subject')}")

        self.interested_emails_queue.sort(key=lambda e: e.get('timestamp_created', ''), reverse=True)
        self.non_interested_emails_queue.sort(key=lambda e: e.get('timestamp_created', ''), reverse=True)
        self.update_queue_widgets()
        self.log(f"Trovati {len(self.interested_emails_queue)} lead interessati e {len(self.non_interested_emails_queue)} non interessati.")

        if not self.current_email:
            self.load_next_email()

    def update_queue_widgets(self):
        self.interested_queue_list.clear()
        for email in self.interested_emails_queue:
            item = QListWidgetItem(f"{email.get('from_address_email')} - {email.get('subject', 'No Subject')}")
            item.setData(Qt.ItemDataRole.UserRole, email.get('id'))
            self.interested_queue_list.addItem(item)
        self.non_interested_queue_list.clear()
        for email in self.non_interested_emails_queue:
            item = QListWidgetItem(f"{email.get('from_address_email')} - {email.get('subject', 'No Subject')}")
            item.setData(Qt.ItemDataRole.UserRole, email.get('id'))
            self.non_interested_queue_list.addItem(item)
        self.update_list_counters()

    def update_list_counters(self):
        self.interested_queue_label.setText(f"Lead interessati: {self.interested_queue_list.count()}")
        self.non_interested_queue_label.setText(f"Lead non interessati: {self.non_interested_queue_list.count()}")

    def get_email_by_id(self, email_id):
        for email in self.interested_emails_queue:
            if email.get('id') == email_id:
                return email
        for email in self.non_interested_emails_queue:
            if email.get('id') == email_id:
                return email
        return None

    def email_selected_interested(self, item):
        email_id = item.data(Qt.ItemDataRole.UserRole)
        email = self.get_email_by_id(email_id)
        if email:
            self.current_email = email
            self.current_email_label.setText(f"Email corrente: {email.get('from_address_email')}")
            content = email.get('body', {}).get('text', '') or email.get('content_preview', '')
            self.client_response_text.setText(content)
            self.update_button_states(True)

    def email_selected_non_interested(self, item):
        email_id = item.data(Qt.ItemDataRole.UserRole)
        email = self.get_email_by_id(email_id)
        if email:
            self.current_email = email
            self.current_email_label.setText(f"Email corrente: {email.get('from_address_email')}")
            content = email.get('body', {}).get('text', '') or email.get('content_preview', '')
            self.client_response_text.setText(content)
            self.update_button_states(True)

    def load_next_email(self):
        if self.interested_emails_queue:
            self.current_email = self.interested_emails_queue.pop(0)
        elif self.non_interested_emails_queue:
            self.current_email = self.non_interested_emails_queue.pop(0)
        else:
            self.current_email = None
            self.current_email_label.setText("Email corrente: Nessuna")
            self.client_response_text.clear()
            self.response_text.clear()
            return
        self.current_email_label.setText(f"Email corrente: {self.current_email.get('from_address_email')}")
        content = self.current_email.get('body', {}).get('text', '') or self.current_email.get('content_preview', '')
        self.client_response_text.setText(content)
        self.update_button_states(True)
        self.update_queue_widgets()
        self.log("Caricata la prossima email interessata.")

    # --- Modifica esclusiva: salvataggio delle risposte in file di testo ---
    def elabora_risposta_ai(self):
        if self.current_email:
            self.log("Elaborazione risposta AI su richiesta manuale...")
            email_content = self.client_response_text.toPlainText()
            ai_response = self.generate_ai_response(email_content)
            if ai_response:
                self.response_text.setText(ai_response)
                # Salvo la risposta AI originale in un attributo dedicato
                self.ai_original_response = ai_response
                self.log("Risposta AI generata con successo")
            else:
                self.log("Errore nella generazione della risposta AI")
        else:
            self.log("Nessuna email selezionata per elaborare risposta AI.")

    def generate_ai_response(self, email_content):
        try:
            self.log("Creazione thread OpenAI...")
            thread = client.beta.threads.create()
            self.log("Invio contenuto email all'AI...")
            message = client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=f"Please generate a response to this email: {email_content}"
            )
            self.log("Avvio elaborazione risposta...")
            run = client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=ASSISTANT_ID
            )
            while run.status != "completed":
                run = client.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run.id)
                self.log(f"Stato elaborazione: {run.status}")
                QApplication.processEvents()
            self.log("Recupero risposta AI...")
            messages = client.beta.threads.messages.list(thread_id=thread.id)
            for message in messages:
                if message.role == "assistant":
                    return message.content[0].text.value
        except Exception as e:
            self.log(f"Errore nella generazione della risposta AI: {str(e)}")
            return None

    def save_responses(self, client_email, original, modified):
        """
        Salva in un file di testo le informazioni relative alla conversazione:
          - Email del cliente
          - Risposta originale AI
          - Risposta modificata dall'utente
        Il file viene salvato nella cartella 'correzioni' con un nome che include il timestamp corrente.
        """
        try:
            directory = 'correzioni'
            if not os.path.exists(directory):
                os.makedirs(directory)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = os.path.join(directory, f"responses_{timestamp}.txt")
            self.log(f"Salvataggio risposte nel file: {filename}")
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("Email del cliente:\n")
                f.write(client_email + "\n\n")
                f.write("Risposta originale AI:\n")
                f.write(original + "\n\n")
                f.write("Risposta modificata:\n")
                f.write(modified + "\n")
                f.write("-" * 50 + "\n")
        except Exception as e:
            self.log(f"Errore nel salvataggio delle risposte: {str(e)}")
    # --- Fine modifica salvataggio ---

    def send_response(self):
        if self.current_email:
            self.log("Preparazione invio risposta...")
            # Recupera il testo originale dell'email del cliente visualizzato
            client_email_text = self.client_response_text.toPlainText()
            # Recupera la risposta AI originale salvata (se presente)
            original_response = getattr(self, 'ai_original_response', '')
            # Recupera la risposta modificata (eventualmente dall'utente)
            modified_response = self.response_text.toPlainText()
            # Salva le informazioni nel file di log
            self.save_responses(client_email_text, original_response, modified_response)
            if self.send_email_response(self.current_email['id'], modified_response, self.current_email):
                self.log("Risposta inviata con successo")
                # Salva l'email nel Google Sheet
                destinatario = self.current_email.get('from_address_email')
                try:
                    salva_email_in_google_sheet(destinatario, '1A5nBCXMgk1hDXHSNnEvshgRj7UfmefBcsyXsUi_2y2M', "ai-agent-450915-5a91975b504e.json")
                except Exception as e:
                    self.log(f"Errore nel salvataggio su Google Sheet: {str(e)}")
                self.mark_as_read()
            else:
                self.log("Errore nell'invio della risposta")
            self.response_text.clear()
            self.client_response_text.clear()
            self.update_button_states(False)
            self.load_next_email()
        else:
            self.log("Nessuna email corrente da inviare risposta.")

    def send_email_response(self, email_id, response_text, email_data):
        prepared_response = prepare_text_for_sending(response_text)
        url = f"{INSTANTLY_BASE_URL}/emails/reply"
        headers = {
            "Authorization": f"Bearer {INSTANTLY_API_KEY}",
            "Content-Type": "application/json"
        }
        from_value = email_data.get('to_address_email_list', '')
        if isinstance(from_value, list):
            from_value = from_value[0] if from_value else ''
        elif isinstance(from_value, str) and ',' in from_value:
            from_value = from_value.split(',')[0]
        data = {
            "reply_to_uuid": email_id,
            "subject": f"Re: {email_data.get('subject', 'No Subject')}",
            "from": from_value,
            "to": email_data.get('from_address_email', ''),
            "body": {"text": prepared_response},
            "eaccount": from_value
        }
        if 'reminder_ts' in email_data:
            data['reminder_ts'] = email_data['reminder_ts']
        try:
            self.log(f"Invio risposta: URL={url}, Data={json.dumps(data)}")
            response = requests.post(url, headers=headers, json=data)
            self.log(f"Risposta API invio: Status={response.status_code}, Content={response.text[:500]}...")
            response.raise_for_status()
            response_data = response.json()
            if response_data.get('id'):
                self.log(f"Risposta inviata con successo. Message ID: {response_data.get('id')}")
                return True
            else:
                self.log("Risposta inviata, ma manca l'ID del messaggio nella risposta")
                return True
        except requests.RequestException as e:
            self.log(f"Errore nell'invio della risposta: {str(e)}")
            return False
        except Exception as e:
            self.log(f"Errore generico nell'invio della risposta: {str(e)}")
            return False

    def mark_as_read(self):
        if self.current_email and self.current_email.get('thread_id'):
            self.log("Segnando la mail come letta...")
            url = f"{INSTANTLY_BASE_URL}/emails/threads/{self.current_email['thread_id']}/mark-as-read"
            headers = {
                "Authorization": f"Bearer {INSTANTLY_API_KEY}",
                "Content-Type": "application/json"
            }
            try:
                self.log(f"Richiesta API per segnare come letta: URL={url}")
                response = requests.post(url, headers=headers, json={})
                self.log(f"Risposta API segnare come letta: Status={response.status_code}, Content={response.text[:500]}...")
                response.raise_for_status()
                self.log("Mail segnata come letta con successo")
            except requests.RequestException as e:
                self.log(f"Errore nel segnare la mail come letta: {str(e)}")
            except Exception as e:
                self.log(f"Errore generico nel segnare la mail come letta: {str(e)}")

    def set_reminder(self):
        if self.current_email:
            options = ["1 giorno", "1 settimana"]
            choice, ok = QInputDialog.getItem(self, "Imposta Reminder", "Scegli quando vuoi il reminder:", options, 0, False)
            if ok and choice:
                current_time = QDateTime.currentDateTime()
                if choice == "1 giorno":
                    reminder_time = current_time.addDays(1)
                elif choice == "1 settimana":
                    reminder_time = current_time.addDays(7)
                reminder_ts = reminder_time.toString("yyyy-MM-ddTHH:mm:ssZ")
                self.log(f"Impostazione reminder per: {reminder_ts}")
                self.current_email['reminder_ts'] = reminder_ts
                self.log("Reminder impostato con successo")
            else:
                self.log("Impostazione reminder annullata")
        else:
            self.log("Nessuna email corrente selezionata per impostare il reminder")

    def skip_email(self):
        if self.current_email:
            self.log(f"Saltata email da: {self.current_email.get('from_address_email')}")
            self.update_button_states(False)
            self.response_text.clear()
            self.client_response_text.clear()
            self.load_next_email()
        else:
            self.log("Nessuna email corrente da saltare")

    def refresh_script(self):
        self.log("Riavvio dello script in corso...")
        self.interested_emails_queue.clear()
        self.non_interested_emails_queue.clear()
        self.interested_queue_list.clear()
        self.non_interested_queue_list.clear()
        self.current_email = None
        self.current_email_label.setText("Email corrente: Nessuna")
        self.client_response_text.clear()
        self.response_text.clear()
        self.update_button_states(False)
        self.check_emails()

def main():
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
