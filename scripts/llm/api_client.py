from dotenv import load_dotenv
import os
from google import genai

load_dotenv()
GOOGLE_API_KEY = os.getenv("GEMINI_API_KEY")
CLIENT = genai.Client(api_key=GOOGLE_API_KEY)