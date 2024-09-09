import requests
import json
from PIL import Image
from io import BytesIO
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from threading import Lock
import base64

# Load configuration from files
spotify_config_file_path = 'spotify_config.json'
trakt_config_file_path = 'config.json'

# Load Spotify and Trakt configurations
def load_config():
    try:
        with open(spotify_config_file_path) as spotify_config_file:
            spotify_config = json.load(spotify_config_file)
        
        with open(trakt_config_file_path) as trakt_config_file:
            trakt_config = json.load(trakt_config_file)
        
        return spotify_config, trakt_config
    except FileNotFoundError as e:
        print(f"Error loading configuration: {e}")
        return None, None
    except json.JSONDecodeError as e:
        print(f"Error parsing configuration files: {e}")
        return None, None

def refresh_spotify_token(config):
    token_url = 'https://accounts.spotify.com/api/token'
    
    client_id = config.get('client_id')
    client_secret = config.get('client_secret')
    refresh_token = config.get('refresh_token')
    
    if not client_id or not client_secret or not refresh_token:
        print("Error: Missing required configuration values.")
        return None
    
    auth_str = f'{client_id}:{client_secret}'
    auth_header = f'Basic {base64.b64encode(auth_str.encode()).decode()}'
    
    payload = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    headers = {
        'Authorization': auth_header,
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        response = requests.post(token_url, data=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        
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

# Initialize global variables
spotify_access_token = None
trakt_headers = {}
previous_poster_url = None
previous_album_art_url = None
previous_watching_state = None
matrix = None
fill_image = True
zoom_percentage = 8
offset_pixels = -10

# Create a lock for the matrix
matrix_lock = Lock()

def setup_matrix():
    global matrix
    options = RGBMatrixOptions()
    options.rows = 64
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = 'adafruit-hat'
    options.brightness = 80
    options.gpio_slowdown = 4
    matrix = RGBMatrix(options=options)

def fetch_current_track(access_token):
    url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 401:  # Unauthorized, possible token expiration
            print("Spotify token expired. Refreshing...")
            new_token = refresh_spotify_token(load_config()[0])
            if new_token:
                global spotify_access_token
                spotify_access_token = new_token
                with open(spotify_config_file_path, 'w') as f:
                    json.dump({'access_token': new_token}, f, indent=4)
                headers['Authorization'] = f'Bearer {new_token}'
                response = requests.get(url, headers=headers)
        
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Spotify API Error: {e}")
        return None

def fetch_album_artwork(image_url):
    try:
        response = requests.get(image_url)
        response.raise_for_status()
        return Image.open(BytesIO(response.content))
    except requests.RequestException as e:
        print(f"Error fetching album artwork: {e}")
        return None

def fetch_currently_watching():
    watching_url = f'https://api.trakt.tv/users/{trakt_username}/watching'
    try:
        response = requests.get(watching_url, headers=trakt_headers)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Error fetching currently watching data: {e}")
        return None

def fetch_poster_from_tmdb(tmdb_id, is_movie=True, season_number=None):
    base_url = 'https://api.themoviedb.org/3'
    endpoint = f"/{'movie' if is_movie else 'tv'}/{tmdb_id}"
    if not is_movie and season_number:
        endpoint += f"/season/{season_number}"
    tmdb_url = f"{base_url}{endpoint}?api_key={tmdb_api_key}"
    try:
        response = requests.get(tmdb_url)
        response.raise_for_status()
        data = response.json()
        poster_path = data.get('poster_path')
        if poster_path:
            return f'https://image.tmdb.org/t/p/original{poster_path}'
    except requests.RequestException as e:
        print(f"Error fetching poster: {e}")
        return None

def resize_image(image, target_size, fill_matrix=True, zoom_percentage=0, offset_pixels=0):
    img_width, img_height = image.size
    target_width, target_height = target_size

    img_aspect = img_width / img_height
    target_aspect = target_width / target_height

    if fill_matrix:
        if img_aspect < target_aspect:
            new_width = target_width
            new_height = int(new_width / img_aspect)
        else:
            new_height = target_height
            new_width = int(new_height * img_aspect)

        if zoom_percentage > 0:
            new_width = int(new_width * (1 + zoom_percentage / 100))
            new_height = int(new_height * (1 + zoom_percentage / 100))

        img = image.resize((new_width, new_height), Image.LANCZOS)
        top = (new_height - target_height) // 2 + offset_pixels
        top = max(top, 0)
        img = img.crop((0, top, target_width, top + target_height))
    else:
        if img_aspect > target_aspect:
            new_width = target_width
            new_height = int(new_width / img_aspect)
        else:
            new_height = target_height
            new_width = int(new_height * img_aspect)

        img = image.resize((new_width, new_height), Image.LANCZOS)
        background = Image.new('RGB', target_size, (0, 0, 0))
        paste_x = (target_width - new_width) // 2
        paste_y = (target_height - new_height) // 2
        background.paste(img, (paste_x, paste_y))
        img = background

    return img

def display_image_on_matrix(image):
    image = resize_image(image, (matrix.width, matrix.height), fill_image, zoom_percentage, offset_pixels)
    image = image.convert('RGB')

    # Lock the matrix for display
    with matrix_lock:
        matrix.Clear()
        matrix.SetImage(image)
        print("Image displayed")

def display_poster(poster_url):
    global previous_poster_url, previous_watching_state

    if poster_url and (poster_url != previous_poster_url or previous_watching_state != 'movie'):
        try:
            image_response = requests.get(poster_url)
            image_response.raise_for_status()
            img = Image.open(BytesIO(image_response.content))
            print(f"Displaying poster: {poster_url}")
            display_image_on_matrix(img)
            previous_poster_url = poster_url
            previous_watching_state = 'movie'
        except requests.RequestException as e:
            print(f"Error fetching or displaying poster: {e}")

def display_album_art(album_art_url):
    global previous_album_art_url, previous_watching_state

    if album_art_url and (album_art_url != previous_album_art_url or previous_watching_state != 'track'):
        try:
            image = fetch_album_artwork(album_art_url)
            if image:
                print(f"Displaying album art: {album_art_url}")
                display_image_on_matrix(image)
                previous_album_art_url = album_art_url
                previous_watching_state = 'track'
        except Exception as e:
            print(f"Error fetching or displaying album art: {e}")

def main():
    global previous_poster_url, previous_album_art_url, previous_watching_state
    global spotify_access_token, trakt_headers, tmdb_api_key, trakt_username

    setup_matrix()
    spotify_config, trakt_config = load_config()

    if spotify_config and trakt_config:
        spotify_access_token = spotify_config['access_token']
        client_id = trakt_config['client_id']
        tmdb_api_key = trakt_config['tmdb_api_key']
        trakt_username = trakt_config['trakt_username']

        trakt_headers = {
            'Content-Type': 'application/json',
            'trakt-api-key': client_id,
            'trakt-api-version': '2',
        }

        while True:
            # Fetch data from both sources
            track_data = fetch_current_track(spotify_access_token)
            watching_data = fetch_currently_watching()

            # Determine if track data or watching data is available
            track_is_playing = track_data and 'item' in track_data and track_data['is_playing']
            watching_is_playing = watching_data and 'type' in watching_data

            # Display album art if playing
            if track_is_playing:
                album_art_url = track_data['item']['album']['images'][0]['url']
                print(f"Currently playing track: {track_data['item']['name']}")
                display_album_art(album_art_url)
            # Display movie poster if watching
            elif watching_is_playing:
                media_type = watching_data.get('type')
                if media_type == 'movie':
                    movie_id = watching_data.get('movie', {}).get('ids', {}).get('tmdb')
                    if movie_id:
                        poster_url = fetch_poster_from_tmdb(movie_id, is_movie=True)
                        print(f"Currently watching movie: {watching_data.get('movie', {}).get('title')}")
                        display_poster(poster_url)
                elif media_type == 'episode':
                    episode = watching_data.get('episode')
                    show_id = watching_data.get('show', {}).get('ids', {}).get('tmdb')
                    if episode and show_id:
                        season_number = episode.get('season')
                        if season_number:
                            poster_url = fetch_poster_from_tmdb(show_id, is_movie=False, season_number=season_number)
                            print(f"Currently watching episode: S{season_number}E{episode.get('number')}")
                            display_poster(poster_url)
            else:
                print("Display cleared")
                with matrix_lock:
                    matrix.Clear()
                previous_watching_state = None  # Reset watching state when nothing is playing

            # Sleep before the next check
            time.sleep(10)
    else:
        print("Error loading configuration. Exiting.")

if __name__ == '__main__':
    main()
