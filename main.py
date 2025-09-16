import speech_recognition as sr
import pyttsx3
import gradio as gr
import time
from groq import Groq
import json
from datetime import datetime
import requests
import threading
from queue import Queue, Empty
import asyncio

# =============================================================================
# API KEYS - 
# =============================================================================
GROQ_API_KEY = ""  # This is the placeholder for a GROQ key
GEMINI_API_KEY = ""  # Optional 
ELEVENLAB_API_KEY ="" # This is the placeholder a ELEVENLAB key

# ElevenLabs Voice Settings
VOICE_ID = "h061KGyOtpLYDxcoi8E3"
MODEL_ID = "eleven_multilingual_v2"

# =============================================================================
# MEDICAL QUESTIONS
# =============================================================================
QUESTIONS = [
    "What is your age?",
    "What is your profession?", 
    "What health issues are you currently facing?",
    "How long have you been facing this problem?",
    "On a scale of 1 to 10, how severe is your pain?",
    "Have you taken any medications for this problem?",
    "Have you eaten outside food in the last few days?",
    "Have you been in contact with any sick person recently?",
    "Do you have any chronic health conditions?",
    "Is there anything else about your health?"
]

# Global variables
consultation_state = {
    "responses": [],
    "current_question": 0,
    "status": "ready",
    "summary": "",
    "dashboard": "",
    "is_running": False,
    "progress_text": "Ready to start consultation",
    "last_question": "",
    "last_answer": ""
}

def speak_text(text):
    """Text-to-speech with timeout and multiple fallback methods"""
    print(f"🗣️ Speaking: {text}")
    
    # Method 1: Try pyttsx3 with timeout
    success = False
    try:
        print("🔊 Trying local TTS...")
        
        import threading
        import time
        
        def tts_worker():
            nonlocal success
            try:
                engine = pyttsx3.init()
                engine.setProperty('rate', 140)
                engine.setProperty('volume', 1.0)
                engine.say(text)
                engine.runAndWait()
                engine.stop()
                success = True
                print("✅ pyttsx3 TTS completed")
            except Exception as e:
                print(f"❌ pyttsx3 TTS failed in thread: {e}")
        
        # Run TTS in thread with timeout
        tts_thread = threading.Thread(target=tts_worker, daemon=True)
        tts_thread.start()
        tts_thread.join(timeout=5.0)  # 5 second timeout
        
        if tts_thread.is_alive():
            print("⏰ pyttsx3 TTS timed out after 5 seconds")
            success = False
        elif success:
            return True
            
    except Exception as e:
        print(f"❌ pyttsx3 setup failed: {e}")
    
    # Method 2: Windows SAPI (if Windows)
    if not success:
        try:
            import os
            import platform
            if platform.system() == "Windows":
                print("🔊 Trying Windows SAPI...")
                # Escape quotes in text
                escaped_text = text.replace('"', '""')
                cmd = f'powershell -Command "Add-Type -AssemblyName System.Speech; $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; $synth.Speak(\'{escaped_text}\')"'
                result = os.system(cmd)
                if result == 0:
                    print("✅ Windows SAPI TTS completed")
                    success = True
                else:
                    print("❌ Windows SAPI failed")
        except Exception as e:
            print(f"❌ Windows SAPI error: {e}")
    
    # Method 3: System say command (macOS/Linux)
    if not success:
        try:
            import os
            import platform
            system = platform.system()
            if system == "Darwin":  # macOS
                print("🔊 Trying macOS say command...")
                os.system(f'say "{text}"')
                success = True
                print("✅ macOS say completed")
            elif system == "Linux":
                print("🔊 Trying Linux espeak...")
                result = os.system(f'espeak "{text}" 2>/dev/null')
                if result == 0:
                    success = True
                    print("✅ Linux espeak completed")
                else:
                    print("❌ espeak not available")
        except Exception as e:
            print(f"❌ System TTS error: {e}")
    
    # Method 4: Just print the text prominently if all TTS fails
    if not success:
        print("\n" + "="*60)
        print("🚨 VOICE FAILED - PLEASE READ THIS QUESTION:")
        print(f"📢 QUESTION: {text}")
        print("="*60)
        print("💡 Please read the question above and give your answer")
        success = True  # Consider this successful since user can read
    
    return success

def listen_for_speech(timeout=10):
    """Listen for speech input with better error handling and shorter timeout"""
    try:
        recognizer = sr.Recognizer()
        
        # Try to find the best microphone
        mic_list = sr.Microphone.list_microphone_names()
        print(f"🎤 Available microphones: {len(mic_list)} found")
        
        microphone = sr.Microphone()
        
        # Faster ambient noise adjustment
        print("🔇 Quick ambient noise adjustment...")
        with microphone as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.5)
        
        print(f"🎤 LISTENING FOR {timeout} SECONDS... SPEAK NOW!")
        print("📢 Say your answer clearly and loudly!")
        
        # Listen for audio with timeout
        with microphone as source:
            # Use shorter phrase time limit to avoid hanging
            audio = recognizer.listen(source, timeout=timeout, phrase_time_limit=8)
        
        print("🔄 Processing your speech...")
        text = recognizer.recognize_google(audio, language="en-US")
        print(f"✅ UNDERSTOOD: '{text}'")
        return text.strip()
        
    except sr.WaitTimeoutError:
        print(f"⏰ No speech detected in {timeout} seconds")
        return "No response (timeout)"
    except sr.UnknownValueError:
        print("❓ Could not understand what you said")
        return "Could not understand"
    except sr.RequestError as e:
        print(f"❌ Speech recognition service error: {e}")
        return "Speech recognition error"
    except Exception as e:
        print(f"❌ Audio error: {e}")
        return "Audio system error"

def run_single_question(question_num):
    """Run a single question with better error handling and timeouts"""
    global consultation_state
    
    if question_num >= len(QUESTIONS):
        return None
    
    question = QUESTIONS[question_num]
    consultation_state["current_question"] = question_num + 1
    consultation_state["last_question"] = question
    
    print(f"\n🔹 QUESTION {question_num + 1}/10 🔹")
    print(f"❓ {question}")
    
    # Update progress
    consultation_state["progress_text"] = f"Question {question_num + 1}/10: {question}"
    
    # Speak the question with timeout protection
    print("🗣️ About to speak question...")
    
    # Try speaking with timeout
    speak_success = False
    try:
        import signal
        
        def timeout_handler(signum, frame):
            raise TimeoutError("TTS timeout")
        
        # Set 10 second timeout for TTS
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)
        
        speak_success = speak_text(question)
        
        signal.alarm(0)  # Cancel timeout
        
    except (TimeoutError, AttributeError):
        # AttributeError: signal not available on Windows
        print("⏰ TTS timeout or not available, using fallback...")
        speak_success = speak_text(question)  # Try without timeout
    except Exception as e:
        print(f"❌ TTS error: {e}")
        speak_success = False
    
    if not speak_success:
        # Fallback: Display question prominently
        print("\n" + "🚨" * 20)
        print(f"📢 QUESTION {question_num + 1}: {question}")
        print("🚨" * 20 + "\n")
    
    # Shorter preparation countdown - CHANGED TO 1 SECOND
    print("⏳ Get ready to answer...")
    consultation_state["progress_text"] = f"Question {question_num + 1}/10: Get ready... (1 second)"
    
    for i in range(1, 0, -1):  # Changed from 2 to 1 second
        print(f"   🔢 {i}...")
        time.sleep(1)
    
    # Clear instruction for listening
    print("🎤 SPEAK YOUR ANSWER NOW!")
    print("📢 You have 8 seconds to respond...")
    consultation_state["progress_text"] = f"Question {question_num + 1}/10: 🎤 LISTENING (8 seconds)"
    
    # Listen for answer with shorter timeout
    answer = listen_for_speech(timeout=8)  # Reduced from 10 to 8 seconds
    
    # Record response
    response_data = {
        "q_num": question_num + 1,
        "question": question,
        "answer": answer,
        "timestamp": datetime.now().strftime("%H:%M:%S")
    }
    
    consultation_state["responses"].append(response_data)
    consultation_state["last_answer"] = answer
    
    print(f"📝 ANSWER RECORDED: '{answer}'")
    consultation_state["progress_text"] = f"Question {question_num + 1}/10: Recorded '{answer}'"
    
    # Give feedback on answer quality
    if answer in ["No response (timeout)", "Could not understand", "Audio system error"]:
        print(f"⚠️ Answer not captured: {answer}")
        print("💡 The consultation will continue to the next question")
    else:
        print(f"✅ Good answer captured!")
    
    return response_data

def generate_analytical_insights(valid_responses):
    """Generate intelligent medical insights using LLM analysis"""
    if not GROQ_API_KEY or GROQ_API_KEY.strip() == "" or len(valid_responses) == 0:
        return "Insufficient data or API key for analytical insights."
    
    try:
        client = Groq(api_key=GROQ_API_KEY)
        
        # Prepare patient responses for analysis
        response_data = "\n".join([
            f"Q{r['q_num']}: {r['question']} → Answer: {r['answer']}"
            for r in valid_responses
        ])

        # Prompt Template
        
        prompt = f"""
You are an experienced physician analyzing patient consultation responses. Generate intelligent clinical insights following this exact format:

PATIENT RESPONSES:
{response_data}

Provide analysis in this EXACT structure:

🩺 Analytical Insights from Patient Responses

Pain Profile
[Analyze any pain-related responses, severity, duration, characteristics]

Possible Triggers  
[Identify potential causes or triggers from patient responses]

Medication Response
[Analyze any medication usage mentioned and response]

Chronic Condition Context
[Examine any chronic conditions and their potential impact]

Risk Assessment  
[Assess clinical urgency and identify any red flags]

🔍 What Physician May Probe Further
[List specific follow-up questions physician should ask]

CRITICAL INSTRUCTIONS:
- Only analyze information explicitly provided by the patient
- Use medical reasoning to connect symptoms and responses
- Be specific about clinical findings and patterns
- Suggest logical follow-up questions
- Do not speculate beyond provided information
- Keep insights practical and clinically relevant
"""
        
        response = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.1-8b-instant",  
            temperature=0.2,
            max_tokens=1000
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        print(f"❌ Analytical insights generation failed: {e}")
        return "Unable to generate analytical insights due to technical error."

def generate_medical_summary():
    """Generate analytical insights instead of traditional summary"""
    responses = consultation_state["responses"]
    valid_responses = [r for r in responses if r['answer'] not in [
        "No response (timeout)", "Could not understand", "Audio system error", 
        "Speech recognition error", "Audio error"
    ]]
    
    valid_count = len(valid_responses)
    total_count = len(responses)
    
    print(f"📊 Generating analytical insights: {valid_count}/{total_count} valid responses")
    
    if valid_count == 0:
        return "No valid patient responses were captured. Unable to generate analytical insights."
    
    # Generate intelligent medical insights using LLM
    return generate_analytical_insights(valid_responses)

def start_consultation():
    """Start consultation - returns immediate feedback"""
    global consultation_state
    
    if consultation_state["is_running"]:
        return (
            "⚠️ Consultation Already Running",
            consultation_state["progress_text"],
            f"Current progress: Question {consultation_state['current_question']}/10"
        )
    
    # Reset state
    consultation_state.update({
        "responses": [],
        "current_question": 0,
        "status": "starting",
        "is_running": True,
        "progress_text": "Starting consultation...",
        "last_question": "",
        "last_answer": ""
    })
    
    # Start background consultation
    def consultation_worker():
        try:
            print("\n" + "="*60)
            print("🚀 STARTING MEDICAL CONSULTATION")
            print("="*60)
            
            consultation_state["status"] = "running"
            
            # Run all questions
            for i in range(len(QUESTIONS)):
                if not consultation_state["is_running"]:
                    break
                
                run_single_question(i)
                
                # Small pause between questions
                if i < len(QUESTIONS) - 1:
                    consultation_state["progress_text"] = f"Moving to question {i + 2}/10..."
                    print("⏸️ Moving to next question...")
                    time.sleep(2)
            
            # Consultation complete
            if consultation_state["is_running"]:
                completed_count = len(consultation_state["responses"])
                print(f"\n🏁 CONSULTATION FINISHED! ({completed_count}/{len(QUESTIONS)} questions)")
                
                # Thank you message
                thank_you = f"Thank you for completing {completed_count} questions. Generating your medical summary now."
                print(f"🗣️ {thank_you}")
                speak_text(thank_you)
                
                # Generate summary
                consultation_state["progress_text"] = "Generating comprehensive medical analysis..."
                print("🧠 Generating medical analysis...")
                consultation_state["summary"] = generate_medical_summary()
                consultation_state["dashboard"] = create_physician_dashboard()
                consultation_state["status"] = "complete"
                consultation_state["progress_text"] = f"✅ Consultation completed! {completed_count}/10 questions answered. Check results below."
                
                print("✅ MEDICAL ANALYSIS COMPLETE!")
                print("✅ PHYSICIAN DASHBOARD READY!")
                print("📊 Click 'Check Progress' to view detailed results!")
            else:
                consultation_state["status"] = "stopped"
                consultation_state["progress_text"] = "Consultation was stopped by user"
            
        except Exception as e:
            print(f"❌ Consultation error: {e}")
            consultation_state["status"] = "error"
            consultation_state["progress_text"] = f"Error: {str(e)}"
        finally:
            consultation_state["is_running"] = False
    
    # Start in background thread
    thread = threading.Thread(target=consultation_worker, daemon=True)
    thread.start()
    
    return (
        "🚀 CONSULTATION STARTED!",
        "The automatic consultation has begun. Watch the progress below and listen for questions.",
        "Question 1/10 will begin shortly..."
    )

def check_progress():
    """Check current consultation progress"""
    global consultation_state
    
    status = consultation_state["status"]
    current_q = consultation_state["current_question"]
    total_responses = len(consultation_state["responses"])
    
    # Build progress display
    if status == "complete":
        return (
            "🏁 CONSULTATION COMPLETE!",
            consultation_state["dashboard"],
            f"✅ All {total_responses} questions completed successfully!"
        )
    
    elif status == "running" or consultation_state["is_running"]:
        # Real-time progress
        progress_display = f"""🔄 **Consultation Active**

📋 **Current Status:**
• Question: {current_q}/10
• Completed: {total_responses}/10 responses recorded
• Last Question: {consultation_state.get('last_question', 'Starting...')}  
• Last Answer: {consultation_state.get('last_answer', 'Waiting...')}

⏳ **Current Activity:** {consultation_state['progress_text']}

🎯 **What to do:**
- Listen for questions (they're being spoken aloud)
- Wait for 1-second countdown
- Speak clearly when prompted
- Let the system continue automatically

⚠️ **If you don't hear questions:** Check your computer's speaker volume!"""
        
        return (
            f"🔄 Question {current_q}/10 Running...",
            progress_display,
            consultation_state['progress_text']
        )
    
    elif status == "error":
        return (
            "❌ Error Occurred",
            f"""⚠️ **Consultation Error**

🔧 **What went wrong:**
{consultation_state.get('progress_text', 'Unknown error')}

💡 **Solutions:**
• Check microphone permissions
• Ensure no other apps are using microphone  
• Restart the consultation
• Check speaker volume for questions

📋 **Partial Results:**
{total_responses} questions were completed before the error.""",
            "Error - restart needed"
        )
    
    else:
        return (
            "❓ No Active Consultation",
            "Click 'Start Consultation' to begin the medical interview.",
            "Ready to start"
        )

def stop_consultation():
    """Stop the running consultation"""
    global consultation_state
    consultation_state["is_running"] = False
    consultation_state["status"] = "stopped"
    
    return (
        "🛑 Consultation Stopped", 
        "The consultation has been stopped. Click 'Start Consultation' to begin a new one.",
        "Stopped"
    )

def create_physician_dashboard():
    """Create streamlined physician dashboard with analytical insights"""
    responses = consultation_state["responses"]
    valid_responses = [r for r in responses if r['answer'] not in [
        "No response (timeout)", "Could not understand", "Audio system error", 
        "Speech recognition error", "Audio error"
    ]]
    
    valid_count = len(valid_responses)
    total_count = len(responses)
    
    # Determine data quality status (Set Threhold)
    if valid_count >= 7:
        quality_status = "🟢 GOOD"
        completion_rate = f"{(valid_count/total_count)*100:.0f}%"
    elif valid_count >= 4:
        quality_status = "🟡 FAIR" 
        completion_rate = f"{(valid_count/total_count)*100:.0f}%"
    else:
        quality_status = "🔴 POOR"
        completion_rate = f"{(valid_count/total_count)*100:.0f}%"
    
    dashboard = f"""# 🏥 PHYSICIAN CONSULTATION DASHBOARD

## 📊 CONSULTATION SUMMARY
- **Date:** {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
- **Data Quality:** {quality_status}
- **Completion Rate:** {completion_rate} ({valid_count}/{total_count} responses)

---

## {consultation_state['summary']}

---

## 📝 COMPLETE RESPONSE RECORD

### ✅ PATIENT RESPONSES CAPTURED:
"""
    
    if valid_count == 0:
        dashboard += "**No responses were successfully captured.**\n\n"
    else:
        for r in valid_responses:
            dashboard += f"**Q{r['q_num']}:** {r['question']}\n"
            dashboard += f"**Answer:** {r['answer']}\n"
            dashboard += f"*Time: {r['timestamp']}*\n\n"
    
    # Show failed responses only if there are any
    failed_responses = [r for r in responses if r['answer'] in [
        "No response (timeout)", "Could not understand", "Audio system error", 
        "Speech recognition error", "Audio error"
    ]]
    
    if failed_responses:
        dashboard += f"### ❌ FAILED TO CAPTURE ({len(failed_responses)} questions):\n"
        for r in failed_responses:
            dashboard += f"**Q{r['q_num']}:** {r['question']} → {r['answer']}\n"
    
    dashboard += f"""

---
*Generated by AI Medical Consultation System | {valid_count}/{total_count} responses analyzed*"""
    
    return dashboard

def create_gradio_interface():
    """Create the main Gradio interface"""
    
    with gr.Blocks(title="Medical Voice Consultation", theme=gr.themes.Soft()) as demo:
        
        gr.Markdown("# 🏥 Automatic Medical Voice Consultation")
        gr.Markdown("*AI-Powered Medical Interview with Real-Time Progress*")
        
        # System status
        def check_system_status():
            status = []
            
            # API Status
            if GROQ_API_KEY and GROQ_API_KEY.strip():
                status.append("✅ **AI Analysis**: Groq configured")
            else:
                status.append("⚪ **AI Analysis**: Basic mode (add Groq key for advanced)")
            
            if ELEVENLAB_API_KEY and ELEVENLAB_API_KEY.strip():
                status.append("✅ **Voice**: ElevenLabs + Local TTS")
            else:
                status.append("⚪ **Voice**: Local TTS only")
            
            # Microphone test
            try:
                r = sr.Recognizer()
                sr.Microphone()
                status.append("✅ **Microphone**: Ready")
            except:
                status.append("❌ **Microphone**: Check permissions")
            
            return "### 🔧 System Status\n" + "\n".join(status)
        
        system_status = gr.Markdown(check_system_status())
        
        # Instructions
        gr.Markdown("""
### 🎯 AUTOMATIC CONSULTATION PROCESS:

**📋 What happens:**
1. System asks all 10 medical questions with voice
2. 1-second preparation after each question
3. 8-second listening period for your answer  
4. Automatically moves to next question
5. Generates physician dashboard when complete

**🎤 Requirements:**
- Working microphone with permissions granted
- Speakers or headphones to hear questions
- Quiet environment for clear speech recognition

**⚠️ Important:** Keep this browser tab active and don't switch away during consultation!
        """)
        
        # Main interface
        with gr.Row():
            with gr.Column(scale=2):
                # Status and controls
                status_title = gr.Markdown("## 🚀 Ready for Medical Consultation")
                status_display = gr.Textbox(
                    label="📊 Current Status",
                    value="Ready to start - Click button below",
                    interactive=False
                )
                progress_display = gr.Textbox(
                    label="⏳ Progress Details", 
                    value="No consultation running",
                    interactive=False
                )
                
                # Control buttons
                with gr.Row():
                    start_btn = gr.Button("🚀 Start Consultation", variant="primary", size="lg")
                    progress_btn = gr.Button("📊 Check Progress", variant="secondary")
                    stop_btn = gr.Button("🛑 Stop", variant="stop")
            
            with gr.Column(scale=1):
                gr.Markdown("### 💡 Live Console Output")
                gr.Markdown("Watch your terminal/command prompt for real-time progress updates during the consultation.")
                
                gr.Markdown("### 🔊 Audio Check")
                gr.Markdown("Make sure you can hear system sounds and your microphone is working before starting.")
        
        # Results area
        with gr.Row():
            results_display = gr.Markdown("### 📋 Results will appear here after consultation")
        
        # Event handlers
        start_btn.click(
            fn=start_consultation,
            outputs=[status_title, status_display, progress_display]
        )
        
        progress_btn.click(
            fn=check_progress,
            outputs=[status_title, results_display, progress_display]
        )
        
        stop_btn.click(
            fn=stop_consultation,
            outputs=[status_title, status_display, progress_display]  
        )
        
        # Questions preview
        with gr.Accordion("📋 Question Preview (3-Question Test)", open=False):
            questions_preview = "\n".join([f"{i+1}. {q}" for i, q in enumerate(QUESTIONS)])
            gr.Markdown(f"**The system will ask these 3 test questions:**\n\n{questions_preview}")
            gr.Markdown("*7 additional questions are commented out until this test version works properly.*")
        
        # Troubleshooting
        with gr.Accordion("🔧 Troubleshooting Guide", open=False):
            gr.Markdown("""
**🎤 No Questions Heard:**
- Check computer speaker/headphone volume
- Ensure browser has audio permissions
- Try refreshing the page

**🗣️ Speech Not Recognized:**
- Grant microphone permissions to browser
- Speak clearly and loudly
- Use quiet environment
- Check microphone is not muted

**🔄 Process Stuck:**
- Watch console output for detailed progress
- Don't switch browser tabs during consultation
- Wait full 8 seconds during listening phases
- Click "Check Progress" to see current status

**⚡ Performance Issues:**
- Close other applications using microphone
- Use wired headset instead of laptop mic
- Ensure stable internet connection
            """)
    
    return demo

def main():
    """Main application"""
    print("🏥 MEDICAL VOICE PRECONSULTATION SYSTEM v2.0")
    print("=" * 55)
    print("🎯 FIXED VERSION - IMPROVED RELIABILITY")
    print("")
    
    # Diagnostic checks
    print("🔧 Pre-flight System Check:")
    
    # Test speech synthesis
    try:
        engine = pyttsx3.init()
        engine.stop()
        print("   ✅ Text-to-Speech: Ready")
    except Exception as e:
        print(f"   ❌ TTS Error: {e}")
    
    # Test speech recognition
    try:
        r = sr.Recognizer()
        mics = sr.Microphone.list_microphone_names()
        print(f"   ✅ Speech Recognition: Ready ({len(mics)} microphones found)")
    except Exception as e:
        print(f"   ❌ Microphone Error: {e}")
    
    # API status
    groq_status = "✅ Configured" if GROQ_API_KEY and GROQ_API_KEY.strip() else "⚪ Not configured"
    eleven_status = "✅ Configured" if ELEVENLAB_API_KEY and ELEVENLAB_API_KEY.strip() else "⚪ Not configured"
    print(f"   🤖 Groq AI: {groq_status}")
    print(f"   🔊 ElevenLabs: {eleven_status}")
    
    print("")
    print("🚀 Starting web interface...")
    print("📍 Interface will open in your browser")
    print("")
    print("📋 IMPORTANT USAGE NOTES:")
    print("   • Keep the console window open to monitor progress")
    print("   • Questions will be spoken - ensure your speakers work") 
    print("   • Grant microphone permissions when browser asks")
    print("   • Stay on the browser tab during consultation")
    print("   • Check 'Progress' frequently for updates")
    print("")
    
    # Launch interface
    try:
        demo = create_gradio_interface()
        demo.launch(
            server_port=7860,
            inbrowser=True,
            share=False,
            show_error=True
        )
    except OSError:
        print("🔄 Port 7860 busy, trying 7861...")
        try:
            demo = create_gradio_interface()
            demo.launch(
                server_port=7861,
                inbrowser=True,
                share=False,
                show_error=True
            )
        except Exception as e:
            print(f"❌ Could not start interface: {e}")

if __name__ == "__main__":
    main()


