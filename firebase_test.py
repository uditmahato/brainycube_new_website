import firebase_admin
from firebase_admin import credentials
import os
import base64
import json

try:
    firebase_credentials_base64 = os.getenv('FIREBASE_CREDENTIALS_BASE64')
    if not firebase_credentials_base64:
        raise ValueError("FIREBASE_CREDENTIALS_BASE64 not set")
    
    # Decode base64 and parse JSON
    credentials_json_str = base64.b64decode(firebase_credentials_base64).decode('utf-8')
    print("Decoded JSON string:", credentials_json_str)  # Debug output
    cred_info = json.loads(credentials_json_str)
    
    # Save to a temporary file for manual inspection
    with open('decoded_credentials.json', 'w') as f:
        json.dump(cred_info, f, indent=2)
    
    # Initialize Firebase
    cred = credentials.Certificate(cred_info)
    firebase_admin.initialize_app(cred)
    print("Firebase Admin SDK initialized successfully!")
except Exception as e:
    print(f"Error: {str(e)}")