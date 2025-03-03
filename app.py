import streamlit as st
import PyPDF2
import re
from datetime import datetime, timedelta
import pytz
import uuid
import pandas as pd
import base64
from typing import Dict, Set, Tuple, List
import calendar
import io
import json
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Optimize Streamlit performance
st.set_page_config(page_title="MCC Timetable Generator", page_icon="📅", layout="wide")
st.cache_resource = st.cache_data  # Use cache_data instead of cache for better performance

# Custom CSS for better styling
st.markdown("""
    <style>
    .main {
        padding: 2rem;
        max-width: 1200px;
        margin: 0 auto;
    }
    .stButton>button {
        border-radius: 12px;
        padding: 0.5rem 1rem;
        background-color: #007AFF;
        color: white;
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #0056b3;
        transform: translateY(-2px);
    }
    .upload-container {
        border: 2px dashed #ccc;
        border-radius: 15px;
        padding: 2rem;
        text-align: center;
        margin: 1rem 0;
        cursor: pointer;
        transition: all 0.3s ease;
    }
    .upload-container:hover {
        border-color: #007AFF;
        background-color: rgba(0, 122, 255, 0.05);
    }
    .css-1d391kg {
        border-radius: 15px;
    }
    .stTextInput>div>div>input {
        border-radius: 10px;
    }
    .stTextArea>div>div>textarea {
        border-radius: 10px;
    }
    .css-1v0mbdj {
        border-radius: 15px;
        padding: 1.5rem;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    .subject-classroom-container {
        background: #f8f9fa;
        border-radius: 10px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .subject-row {
        display: flex;
        align-items: center;
        gap: 1rem;
        margin-bottom: 0.5rem;
    }
    </style>
    <script>
    const dropContainer = document.querySelector('.upload-container');
    
    dropContainer.addEventListener('dragover', e => {
        e.preventDefault();
        dropContainer.style.borderColor = '#007AFF';
        dropContainer.style.backgroundColor = 'rgba(0, 122, 255, 0.05)';
    });
    
    dropContainer.addEventListener('dragleave', e => {
        e.preventDefault();
        dropContainer.style.borderColor = '#ccc';
        dropContainer.style.backgroundColor = 'transparent';
    });
    
    dropContainer.addEventListener('drop', e => {
        e.preventDefault();
        dropContainer.style.borderColor = '#ccc';
        dropContainer.style.backgroundColor = 'transparent';
        const files = e.dataTransfer.files;
        if (files.length) {
            const fileInput = document.querySelector('.stFileUploader input[type="file"]');
            fileInput.files = files;
            fileInput.dispatchEvent(new Event('change', { bubbles: true }));
        }
    });
    </script>
""", unsafe_allow_html=True)

SCOPES = ['https://www.googleapis.com/auth/calendar.events']
GOOGLE_CLIENT_ID = os.getenv('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.getenv('GOOGLE_CLIENT_SECRET')
REDIRECT_URI = os.getenv('REDIRECT_URI', 'https://tt.madrasco.space')

def initialize_google_auth():
    print(f"Redirect URI: {REDIRECT_URI}")  # Debugging line

    flow = Flow.from_client_config(
        {
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [REDIRECT_URI]  # Ensure this is a valid string
            }
        },
        scopes=SCOPES
    )
    
    flow.redirect_uri = REDIRECT_URI  # Explicitly set redirect_uri
    return flow

def get_google_calendar_service():
    if 'google_creds' not in st.session_state:
        return None
    
    creds = Credentials.from_authorized_user_info(st.session_state.google_creds, SCOPES)
    
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
            st.session_state.google_creds = json.loads(creds.to_json())
        else:
            return None
            
    return build('calendar', 'v3', credentials=creds)   

class MCCCalendarParser:
    def __init__(self, start_date=None, end_date=None):
        self.start_date = start_date
        self.end_date = end_date
        self.day_orders = {}
        self.holidays = set()
        self.special_events = {}
        self.months = {month.upper(): index for index, month in enumerate(calendar.month_name) if month}
        self.special_event_patterns = [
            r"Staff Study Circle",
            r"ICA Test",
            r"ESE Practicals",
            r"Faculty Development",
            r"Senatus Meeting",
            r"IQAC Review Meeting",
            r"College Scripture Examination",
            r"Deep Woods",
            r"Annual Staff Retreat",
            r"Hall Day"
        ]

    def is_date_in_range(self, date_str: str) -> bool:
        if not (self.start_date and self.end_date):
            return True
        date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
        return self.start_date <= date_obj <= self.end_date

    def extract_month_year(self, text: str) -> Tuple[str, str]:
        month_pattern = r'(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)'
        year_pattern = r'(20\d{2})'
        
        month_match = re.search(month_pattern, text.upper())
        year_match = re.search(year_pattern, text)
        
        if month_match and year_match:
            return month_match.group(1), year_match.group(1)
        return None, None

    def extract_date_info(self, line: str) -> Tuple[str, str, str, str]:
        pattern = r'^\s*(\d{1,2})\s+(MON|TUE|WED|THU|FRI|SAT|SUN)(?:[^0-9]*([1-6])?)?(.*)$'
        match = re.match(pattern, line)
        
        if match:
            date, day, day_order, remaining_text = match.groups()
            special_event = self.extract_special_event(remaining_text)
            return date.strip(), day.strip(), day_order, special_event
        return None, None, None, None

    def extract_special_event(self, text: str) -> str:
        if not text:
            return None
            
        text = text.strip()
        
        holiday_patterns = [
            r'Holiday',
            r'- No Classes',
            r'Pongal',
            r'Christmas',
            r'Diwali',
            r'Bakrid'
        ]
        
        for pattern in holiday_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return f"Holiday: {text}"
                
        for pattern in self.special_event_patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return text.strip()
                
        return None

    def parse_pdf(self, pdf_content) -> Tuple[Dict[str, str], Set[str], Dict[str, str]]:
        current_month = None
        current_year = None
        
        try:
            pdf_reader = PyPDF2.PdfReader(pdf_content)
            
            for page in pdf_reader.pages:
                text = page.extract_text()
                lines = text.split('\n')
                
                for line in lines:
                    month, year = self.extract_month_year(line)
                    if month and year:
                        current_month = month
                        current_year = year
                        continue
                    
                    if current_month and current_year:
                        date_num, day, day_order, special_event = self.extract_date_info(line)
                        
                        if date_num:
                            try:
                                date_obj = datetime(
                                    int(current_year),
                                    self.months[current_month.upper()],
                                    int(date_num)
                                )
                                date_str = date_obj.strftime("%Y-%m-%d")
                                
                                # Only process dates within the selected range
                                if self.is_date_in_range(date_str):
                                    if day_order:
                                        self.day_orders[date_str] = day_order
                                    elif day in ['SAT', 'SUN']:
                                        self.holidays.add(date_str)
                                    
                                    if special_event:
                                        self.special_events[date_str] = special_event
                                        
                            except ValueError as e:
                                st.warning(f"Error processing date: {line} - {str(e)}")
                                
        except Exception as e:
            st.error(f"Error reading PDF: {str(e)}")
            raise
            
        return self.day_orders, self.holidays, self.special_events

class TimetableGenerator:
    def __init__(self, start_date=None, end_date=None):
        self.timezone = pytz.timezone("Asia/Kolkata")
        self.class_timings = [
            ("1st Hour", "13:45", "14:35"),
            ("2nd Hour", "14:35", "15:25"),
            ("3rd Hour", "15:25", "16:15"),
            ("Break", "16:15", "16:35"),
            ("4th Hour", "16:35", "17:25"),
            ("5th Hour", "17:25", "18:15")
        ]
        self.timetable = {}
        self.classroom_mapping = {}
        self.day_orders = {}
        self.start_date = start_date
        self.end_date = end_date

    def set_timetable(self, timetable_data: Dict[str, List[str]]):
        self.timetable = timetable_data

    def set_classroom_mapping(self, mapping: Dict[str, str]):
        self.classroom_mapping = mapping

    def set_day_orders(self, day_orders: Dict[str, str]):
        if self.start_date and self.end_date:
            self.day_orders = {
                date: order for date, order in day_orders.items()
                if self.start_date <= datetime.strptime(date, "%Y-%m-%d").date() <= self.end_date
            }
        else:
            self.day_orders = day_orders

    def generate_event_string(self, subject: str, start_time: str, end_time: str, 
                            date_str: str, class_name: str, special_event: str = None) -> str:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
        end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M")
        
        now = datetime.now(pytz.UTC)
        
        start_str = start_dt.strftime("%Y%m%dT%H%M%S")
        end_str = end_dt.strftime("%Y%m%dT%H%M%S")
        stamp_str = now.strftime("%Y%m%dT%H%M%SZ")
        
        location = self.classroom_mapping.get(subject, "")
        description = f"{class_name} - {subject}"
        if location:
            description += f"\nRoom: {location}"
        if special_event:
            description += f"\nNote: {special_event}"
            
        event_str = f"""BEGIN:VEVENT
DTSTAMP:{stamp_str}
DTSTART;TZID=Asia/Kolkata:{start_str}
DTEND;TZID=Asia/Kolkata:{end_str}
UID:{str(uuid.uuid4())}
DESCRIPTION:{description}
LOCATION:{location}
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:{subject}
TRANSP:OPAQUE
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:Reminder for {subject}
TRIGGER:-PT10M
END:VALARM
END:VEVENT\n"""
        return event_str

    def generate_holiday_event(self, date_str: str, holiday_name: str = "No Classes") -> str:
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        next_day = date_obj + timedelta(days=1)
        
        now = datetime.now(pytz.UTC)
        stamp_str = now.strftime("%Y%m%dT%H%M%SZ")
        
        date_str_formatted = date_obj.strftime("%Y%m%d")
        next_day_formatted = next_day.strftime("%Y%m%d")
        
        return f"""BEGIN:VEVENT
DTSTAMP:{stamp_str}
DTSTART;VALUE=DATE:{date_str_formatted}
DTEND;VALUE=DATE:{next_day_formatted}
UID:holiday-{date_str_formatted}@college
DESCRIPTION:{holiday_name}
SEQUENCE:0
STATUS:CONFIRMED
SUMMARY:{holiday_name}
TRANSP:TRANSPARENT
END:VEVENT\n"""

    def generate_timetable_ics(self, special_events: Dict[str, str]) -> str:
        ics_content = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//MCC//Timetable Generator//EN",
            "CALSCALE:GREGORIAN",
            "METHOD:PUBLISH",
            "BEGIN:VTIMEZONE",
            "TZID:Asia/Kolkata",
            "BEGIN:STANDARD",
            "DTSTART:19700101T000000",
            "TZOFFSETFROM:+0530",
            "TZOFFSETTO:+0530",
            "TZNAME:IST",
            "END:STANDARD",
            "END:VTIMEZONE"
        ]
        
        for date_str, day_order in sorted(self.day_orders.items()):
            if day_order in self.timetable:
                subjects = self.timetable[day_order]
                subject_index = 0
                
                special_event = special_events.get(date_str)
                
                for class_name, start_time, end_time in self.class_timings:
                    if class_name != "Break" and subject_index < len(subjects):
                        event_str = self.generate_event_string(
                            subjects[subject_index],
                            start_time,
                            end_time,
                            date_str,
                            class_name,
                            special_event
                        )
                        ics_content.append(event_str)
                        subject_index += 1
            else:
                holiday_name = special_events.get(date_str, "No Classes")
                holiday_event = self.generate_holiday_event(date_str, holiday_name)
                ics_content.append(holiday_event)
        
        ics_content.append("END:VCALENDAR")
        return "\n".join(ics_content)
    
    def add_to_google_calendar(self, special_events: Dict[str, str]):
        service = get_google_calendar_service()
        if not service:
            raise Exception("Google Calendar service not initialized")
            
        added_events = 0
        
        for date_str, day_order in sorted(self.day_orders.items()):
            if day_order in self.timetable:
                subjects = self.timetable[day_order]
                subject_index = 0
                special_event = special_events.get(date_str)
                
                for class_name, start_time, end_time in self.class_timings:
                    if class_name != "Break" and subject_index < len(subjects):
                        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
                        start_dt = datetime.strptime(f"{date_str} {start_time}", "%Y-%m-%d %H:%M")
                        end_dt = datetime.strptime(f"{date_str} {end_time}", "%Y-%m-%d %H:%M")
                        
                        event = {
                            'summary': subjects[subject_index],
                            'description': f"{class_name}\n{special_event if special_event else ''}",
                            'start': {
                                'dateTime': start_dt.isoformat(),
                                'timeZone': 'Asia/Kolkata',
                            },
                            'end': {
                                'dateTime': end_dt.isoformat(),
                                'timeZone': 'Asia/Kolkata',
                            },
                            'reminders': {
                                'useDefault': False,
                                'overrides': [
                                    {'method': 'popup', 'minutes': 10},
                                ],
                            },
                        }
                        
                        service.events().insert(calendarId='primary', body=event).execute()
                        added_events += 1
                        subject_index += 1
        
        return added_events

def main():
    st.title("🎓 MCC Timetable Generator")
    st.markdown("---")
    
    # Initialize session state
    if 'parsed_data' not in st.session_state:
        st.session_state.parsed_data = None
    if 'subject_classrooms' not in st.session_state:
        st.session_state.subject_classrooms = {}
        
    # Date Range Selection
    col_date1, col_date2 = st.columns(2)
    with col_date1:
        start_date = st.date_input("Start Date", datetime.now())
    with col_date2:
        end_date = st.date_input("End Date", datetime.now() + timedelta(days=120))
        
    # Google Calendar Authentication Status
    if 'google_creds' not in st.session_state:
        if st.button("Connect Google Calendar"):
            flow = initialize_google_auth()
            authorization_url, _ = flow.authorization_url(prompt='consent')
            st.markdown(f'<a href="{authorization_url}" target="_blank">Click here to authorize</a>', unsafe_allow_html=True)
            auth_code = st.text_input("Enter the authorization code:")
            if auth_code:
                try:
                    flow.fetch_token(code=auth_code)
                    st.session_state.google_creds = json.loads(flow.credentials.to_json())
                    st.success("Successfully connected to Google Calendar!")
                except Exception as e:
                    st.error(f"Error connecting to Google Calendar: {str(e)}")
    else:
        st.success("✅ Connected to Google Calendar")
        if st.button("Disconnect Google Calendar"):
            del st.session_state.google_creds
            st.experimental_rerun()
    
    st.markdown("---")
    pdf_file = st.file_uploader("Upload Calendar PDF", type=['pdf'])
    
    if pdf_file:
        with st.spinner("Parsing PDF..."):
            parser = MCCCalendarParser(start_date=start_date, end_date=end_date)
            try:
                day_orders, holidays, special_events = parser.parse_pdf(pdf_file)
                st.session_state.parsed_data = {
                    'day_orders': day_orders,
                    'holidays': holidays,
                    'special_events': special_events
                }
                st.success("✅ Calendar PDF parsed successfully!")
            except Exception as e:
                st.error(f"❌ Error parsing PDF: {str(e)}")
    
    st.markdown("---")
    
    # Timetable Input with Subject-Classroom Mapping
    col1, col2 = st.columns([1, 1])
    
    with col1:
        st.subheader("📚 Input Timetable")
        timetable_data = {}
        all_subjects = set()
        
        for day_order in range(1, 7):
            with st.expander(f"Day Order {day_order}", expanded=True):
                subjects = st.text_area(
                    f"Subjects",
                    height=100,
                    key=f"day_{day_order}",
                    help="Enter one subject per line (5 subjects)",
                    placeholder="Example:\nCLOUD\nPYTHON\nLAB PYTHON\nPROJECT\nSET"
                )
                if subjects.strip():
                    subject_list = [s.strip() for s in subjects.split('\n') if s.strip()]
                    timetable_data[str(day_order)] = subject_list
                    all_subjects.update(subject_list)
        
        # Classroom Mapping Section
        st.subheader("🏛️ Classroom Mapping")
        with st.expander("Set Classroom Locations", expanded=True):
            for subject in sorted(all_subjects):
                if subject not in st.session_state.subject_classrooms:
                    st.session_state.subject_classrooms[subject] = ""
                    
                st.session_state.subject_classrooms[subject] = st.text_input(
                    f"Room for {subject}",
                    value=st.session_state.subject_classrooms.get(subject, ""),
                    key=f"room_{subject}",
                    placeholder="Enter classroom/lab location"
                )
    
    with col2:
        if st.session_state.parsed_data:
            st.subheader("📅 Calendar Overview")
            
            # Show calendar data in tabs
            tab1, tab2, tab3 = st.tabs(["Day Orders", "Special Events", "Classroom Summary"])
            
            with tab1:
                day_orders_df = pd.DataFrame(
                    [(date, order) for date, order in st.session_state.parsed_data['day_orders'].items()],
                    columns=['Date', 'Day Order']
                )
                st.dataframe(day_orders_df, use_container_width=True)
            
            with tab2:
                events_df = pd.DataFrame(
                    [(date, event) for date, event in st.session_state.parsed_data['special_events'].items()],
                    columns=['Date', 'Event']
                )
                st.dataframe(events_df, use_container_width=True)
                
            with tab3:
                classroom_df = pd.DataFrame(
                    [(subject, room) for subject, room in st.session_state.subject_classrooms.items()],
                    columns=['Subject', 'Room']
                )
                st.dataframe(classroom_df, use_container_width=True)
    
    st.markdown("---")
    
    # Generate Calendar Section
    if st.session_state.parsed_data and timetable_data:
        col3, col4 = st.columns([1, 1])
        
        with col3:
            if st.button("📥 Download Calendar (ICS)"):
                generator = TimetableGenerator(start_date=start_date, end_date=end_date)
                generator.set_timetable(timetable_data)
                generator.set_classroom_mapping(st.session_state.subject_classrooms)
                generator.set_day_orders(st.session_state.parsed_data['day_orders'])
                
                ics_content = generator.generate_timetable_ics(st.session_state.parsed_data['special_events'])
                b64 = base64.b64encode(ics_content.encode()).decode()
                href = f'data:text/calendar;base64,{b64}'
                st.markdown(
                    f'<a href="{href}" download="mcc_timetable.ics" '
                    'class="download-button">⬇️ Download Timetable Calendar</a>',
                    unsafe_allow_html=True
                )
        
        with col4:
            if st.button("📅 Add to Google Calendar"):
                if 'google_creds' not in st.session_state:
                    st.warning("Please connect to Google Calendar first!")
                else:
                    try:
                        generator = TimetableGenerator(start_date=start_date, end_date=end_date)
                        generator.set_timetable(timetable_data)
                        generator.set_classroom_mapping(st.session_state.subject_classrooms)
                        generator.set_day_orders(st.session_state.parsed_data['day_orders'])
                        
                        with st.spinner("Adding events to Google Calendar..."):
                            added_events = generator.add_to_google_calendar(
                                st.session_state.parsed_data['special_events']
                            )
                            st.success(f"✅ Successfully added {added_events} events to Google Calendar!")
                    except Exception as e:
                        st.error(f"❌ Error adding to Google Calendar: {str(e)}")

if __name__ == "__main__":
    main()