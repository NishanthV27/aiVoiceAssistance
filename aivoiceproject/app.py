from flask import Flask, render_template, request, jsonify
import openai
import threading
import queue
import os
import uuid
from gtts import gTTS
import playsound
import webbrowser
from yt_dlp import YoutubeDL
from transformers import pipeline   # ✅ For local LLM

app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-here'

# ✅ OpenRouter API (Cloud LLM)
openai.api_key = "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"
openai.api_base = "https://openrouter.ai/api/v1"

# ✅ Load lightweight local model (DistilGPT2 for text generation)
local_generator = pipeline(
    "text-generation",
    model="distilgpt2",  # can switch to "sshleifer/tiny-gpt2" if you want even smaller
    device=-1            # -1 = CPU, or 0 = GPU if available
)

# ✅ Voice queue
voice_queue = queue.Queue()

# ✅ Microphone active flag
mic_active = True
mic_lock = threading.Lock()


def stop_mic():
    global mic_active
    with mic_lock:
        mic_active = False
    print("🎙️ Mic stopped.")


def start_mic():
    global mic_active
    with mic_lock:
        mic_active = True
    print("🎙️ Mic started.")


def _speak_now(text):
    print("\nAssistant:", text)
    try:
        stop_mic()  # ⛔ Stop mic before speaking
        tts = gTTS(text=text, lang='en')
        filename = f"voice_{uuid.uuid4()}.mp3"
        tts.save(filename)
        playsound.playsound(filename)
        os.remove(filename)
    except Exception as e:
        print("❌ Error in speaking:", e)
    finally:
        start_mic()  # ✅ Restart mic after speaking


def voice_worker():
    while True:
        text = voice_queue.get()
        if text == "___STOP___":
            voice_queue.task_done()
            break
        _speak_now(text)
        voice_queue.task_done()


def speak(text):
    voice_queue.put(text)
    voice_queue.join()


# ✅ Ask cloud LLM
def ask_fast_llm(prompt):
    try:
        response = openai.ChatCompletion.create(
            model="mistralai/mistral-7b-instruct",
            messages=[{"role": "user", "content": prompt}]
        )
        return response['choices'][0]['message']['content']
    except Exception as e:
        print("⚠️ Cloud model error:", e)
        return "Sorry, I couldn't process that."


# ✅ Ask local LLM
def ask_local_llm(prompt):
    try:
        response = local_generator(
            prompt,
            max_length=150,
            num_return_sequences=1,
            temperature=0.7
        )
        return response[0]['generated_text']
    except Exception as e:
        print("⚠️ Local model error:", e)
        return "Sorry, I couldn't process that locally."


# ✅ Commands
def handle_custom_commands(command):
    command = command.lower()

    if any(keyword in command for keyword in ["play song", "play video", "play"]):
        query = command.replace("play", "").replace("song", "").replace("video", "").strip()

        if not query:
            speak("Please tell me what you want to play. For example: 'Play Shape of You'")
            return True

        speak(f"Searching for {query} on YouTube...")

        try:
            ydl_opts = {
                'quiet': True,
                'format': 'bestaudio/best',
                'default_search': 'ytsearch',
            }
            with YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(query, download=False)

                if result and "entries" in result and len(result["entries"]) > 0:
                    video = result["entries"][0]
                    url = video["webpage_url"]
                    speak(f"Playing: {video['title']}")
                    webbrowser.open(url)
                else:
                    speak(f"Sorry, I couldn't find {query} on YouTube.")
        except Exception as e:
            print("❌ YouTube error:", str(e))
            speak("Sorry, I encountered an error while searching YouTube.")

        return True   # 👈 VERY IMPORTANT (stops LLM call later)

    elif "open google" in command:
        speak("Opening Google.")
        webbrowser.open("https://www.google.com")
        return True

    elif "open youtube" in command:
        speak("Opening YouTube.")
        webbrowser.open("https://www.youtube.com")
        return True

    return False



# ✅ Flask routes
@app.route("/")
def home():
    return render_template("index.html")


@app.route("/ask", methods=["POST"])
def ask():
    global mic_active
    data = request.get_json()
    question = data.get("question", "").lower()
    print("User:", question)

    if not mic_active:
        return jsonify({"reply": "", "should_speak": False})

    if not question.strip():
        return jsonify({"reply": "I didn't catch that.", "should_speak": True})

    if "exit" in question:
        speak("Goodbye!")
        voice_queue.put("___STOP___")
        return jsonify({"reply": "Exiting assistant.", "should_speak": False})

    # ✅ Handle commands first
    if handle_custom_commands(question):
        return jsonify({"reply": "", "should_speak": False})

    # ✅ Use local model if user says "local"
    if "local" in question:
        reply = ask_local_llm(question.replace("local", ""))
    else:
        reply = ask_fast_llm(question)

    speak(reply)
    return jsonify({"reply": reply, "should_speak": False})


# ✅ Start voice thread
if __name__ == "__main__":
    threading.Thread(target=voice_worker, daemon=True).start()
    app.run(debug=True)
