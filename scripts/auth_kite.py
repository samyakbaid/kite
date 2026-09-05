import os
import re
from urllib.parse import urlparse, parse_qs

try:
    from kiteconnect import KiteConnect
except ImportError:
    print("Please install kiteconnect: pip install kiteconnect")
    exit(1)

def main():
    env_file = ".env"
    env_content = ""
    if os.path.exists(env_file):
        with open(env_file, "r") as f:
            env_content = f.read()
    
    # Extract API KEY
    api_key_match = re.search(r"KITE_API_KEY=(.+)", env_content)
    if not api_key_match:
        api_key = input("Enter KITE_API_KEY: ").strip()
        env_content += f"\nKITE_API_KEY={api_key}\n"
    else:
        api_key = api_key_match.group(1).strip()

    # Extract API SECRET
    api_secret_match = re.search(r"KITE_API_SECRET=(.+)", env_content)
    if not api_secret_match:
        api_secret = input("Enter KITE_API_SECRET: ").strip()
        # Optionally save it
        save_secret = input("Save API_SECRET in .env? (y/n): ").strip().lower()
        if save_secret == 'y':
            env_content += f"\nKITE_API_SECRET={api_secret}\n"
    else:
        api_secret = api_secret_match.group(1).strip()

    print("\n" + "="*50)
    print("1. Open this URL in your browser to log in to Kite:")
    print(f"   https://kite.trade/connect/login?v=3&api_key={api_key}")
    print("2. After successful login, you will be redirected.")
    print("3. Copy the 'request_token' from the redirected URL.")
    print("="*50 + "\n")

    request_token_url = input("Paste the full redirected URL or just the request_token: ").strip()
    
    if "request_token=" in request_token_url:
        parsed_url = urlparse(request_token_url)
        params = parse_qs(parsed_url.query)
        request_token = params.get("request_token", [request_token_url])[0]
    else:
        request_token = request_token_url

    print("\nGenerating access token...")
    kite = KiteConnect(api_key=api_key)
    try:
        data = kite.generate_session(request_token, api_secret=api_secret)
        access_token = data["access_token"]
        print("Success! Access token generated.")
        
        # Update .env
        if "KITE_ACCESS_TOKEN=" in env_content:
            env_content = re.sub(r"KITE_ACCESS_TOKEN=.*", f"KITE_ACCESS_TOKEN={access_token}", env_content)
        else:
            env_content += f"\nKITE_ACCESS_TOKEN={access_token}\n"
            
        with open(env_file, "w") as f:
            f.write(env_content)
            
        print("Successfully updated .env with the new KITE_ACCESS_TOKEN.")
        
    except Exception as e:
        print(f"Error generating session: {e}")

if __name__ == "__main__":
    main()
