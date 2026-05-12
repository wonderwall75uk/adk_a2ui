import requests
try:
    r = requests.get("https://generativelanguage.googleapis.com", timeout=5)
    print(f"Status: {r.status_code}")
except Exception as e:
    print(f"Error: {e}")
