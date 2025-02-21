import os
import streamlit as st

REDIRECT_URI = os.getenv('REDIRECT_URI', 'Not Set')

st.write(f"Current REDIRECT_URI: {REDIRECT_URI}")