# main.py
import subprocess
import sys
import os
from dotenv import load_dotenv

if __name__ == "__main__":
    load_dotenv()

    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        print("API key not found. Exiting.")
        sys.exit(1)

    # Run the chat application and block until it's finished
    application_process = subprocess.run(["python", "chat.py", api_key])