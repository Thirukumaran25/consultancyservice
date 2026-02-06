import google.generativeai as genai
from django.conf import settings

genai.configure(api_key=settings.GEMINI_API_KEY)

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash-lite",
    system_instruction="Answer in 1 line"
)

def ask_gemini(question):
    try:
        response = model.generate_content(question)
        return response.text.strip()
    except Exception as e:
        print("🔥 GEMINI ERROR:", e)
        return "⚠️ AI service is temporarily unavailable."
