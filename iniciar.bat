@echo off
cd /d "%~dp0"
python -m pip install -q requests pywebview psutil pyperclip pycaw comtypes pillow winrt-runtime winrt-Windows.Media.Control winrt-Windows.Foundation winrt-Windows.Foundation.Collections winrt-Windows.Storage.Streams edge-tts pygame SpeechRecognition PyAudio pyttsx3
python main.py
pause
