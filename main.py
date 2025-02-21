# app.py
from flask import Flask, render_template, request, jsonify, send_file
from werkzeug.utils import secure_filename
import PyPDF2
import os
from datetime import datetime
import json
import uuid
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from dotenv import load_dotenv
from mcc_parser import MCCCalendarParser
from timetable_generator import TimetableGenerator

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('FLASK_SECRET_KEY', 'dev')

# Google Calendar API Setup
SCOPES = ['https://www.googleapis.com/auth/calendar.events']
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'http://localhost:5000/callback')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/parse-pdf', methods=['POST'])
def parse_pdf():
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
        
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
        
    try:
        parser = MCCCalendarParser()
        day_orders, holidays, special_events = parser.parse_pdf(file)
        
        return jsonify({
            'day_orders': day_orders,
            'holidays': list(holidays),
            'special_events': special_events
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/google-auth')
def google_auth():
    try:
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": GOOGLE_CLIENT_ID,
                    "client_secret": GOOGLE_CLIENT_SECRET,
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "redirect_uris": [REDIRECT_URI]
                }
            },
            scopes=SCOPES
        )
        authorization_url, state = flow.authorization_url(prompt='consent')
        return jsonify({'url': authorization_url})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/generate-ics', methods=['POST'])
def generate_ics():
    try:
        data = request.get_json()
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
        generator = TimetableGenerator(start_date=start_date, end_date=end_date)
        generator.set_timetable(data['timetable'])
        generator.set_day_orders(data['day_orders'])
        
        ics_content = generator.generate_timetable_ics(data['special_events'])
        
        return send_file(
            io.BytesIO(ics_content.encode()),
            mimetype='text/calendar',
            as_attachment=True,
            download_name='mcc_timetable.ics'
        )
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
