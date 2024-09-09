import json
import requests
import base64
import os

# Load configuration from spotify_config.json
def load_spotify_config():
    try:
        with open('spotify_config.json', 'r') as f:
            config = json.load(f)
            return config
    except FileNotFoundError:
        print("Error: spotify_config.json file not found.")
        return None
    except json.JSONDecodeError as e:
        print(f"Error parsing spotify_config.json: {e}")
        return None

# Refresh Spotify access token
def refresh_spotify_token(config):
    token_url = 'https://accounts.spotify.com/api/token'
    
    # Get the client credentials and refresh token from config
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')
    refresh_token = config.get('refresh_token')
    
    if not client_id or not client_secret or not refresh_token:
        print("Error: Missing required configuration values.")
        return None
    
    # Base64 encode the client_id and client_secret
    auth_str = f'{client_id}:{client_secret}'
    auth_header = f'Basic {base64.b64encode(auth_str.encode()).decode()}'
    
    # Prepare the payload and headers for the request
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    headers = {
        'Authorization': auth_header,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        # Make the POST request to refresh the token
        response = requests.post(token_url, data=payload, headers=headers)
        print(f"Response Status Code: {response.status_code}")
        print(f"Response Text: {response.text}")
        
        response.raise_for_status()
        data = response.json()
        
        # Extract access token from the response
        if 'access_token' in data:
            new_access_token = data['access_token']
            print(f"New Access Token: {new_access_token}")
            return new_access_token
        else:
            print("Error: No access token found in the response.")
            return None
    except requests.RequestException as e:
        print(f"Spotify token refresh error: {e}")
        return None

def save_config(config):
    try:
        with open('spotify_config.json', 'w') as f:
            json.dump(config, f, indent=4)
        print("Configuration saved successfully.")
    except IOError as e:
        print(f"Error writing to spotify_config.json: {e}")

def main():
    # Load the Spotify configuration
    config = load_spotify_config()
    
    if config:
        # Refresh the Spotify access token
        new_token = refresh_spotify_token(config)
        if new_token:
            # Update the config with the new token and save it
            config['access_token'] = new_token
            save_config(config)
        else:
            print("Failed to refresh Spotify access token.")
    else:
        print("Configuration could not be loaded.")

if __name__ == '__main__':
    main()
