import requests
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from threading import Lock
from datetime import datetime
import base64
import json

# In-memory token storage
token_storage = {
    'access_token': '',
    'refresh_token': '',
    'client_id': '',
    'client_secret': ''
}

# Load Trakt configuration
with open('config.json') as trakt_config_file:
    trakt_config = json.load(trakt_config_file)
client_id = trakt_config['client_id']
tmdb_api_key = trakt_config['tmdb_api_key']
trakt_username = trakt_config['trakt_username']

# Trakt headers
trakt_headers = {
    'Content-Type': 'application/json',
    'trakt-api-key': client_id,
    'trakt-api-version': '2',
}

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
    options.brightness = 60
    options.gpio_slowdown = 4
    matrix = RGBMatrix(options=options)

def update_token_storage(new_tokens):
    """Update the in-memory token storage."""
    token_storage.update(new_tokens)

def fetch_current_track():
    access_token = token_storage.get('access_token')
    url = 'https://api.spotify.com/v1/me/player/currently-playing'
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    response = requests.get(url, headers=headers)
    
    if response.status_code == 204:
        return None  # No content playing
    elif response.status_code == 200:
        return response.json()
    elif response.status_code == 401:
        return handle_token_refresh()  # Handle token refresh on 401
    else:
        print(f"Spotify API Error: {response.status_code} {response.text}")
    return None

def handle_token_refresh():
    """Handle the refresh of Spotify access tokens."""
    refresh_token = token_storage.get('refresh_token')
    client_id = token_storage.get('client_id')
    client_secret = token_storage.get('client_secret')
    
    # Request new access token
    token_url = 'https://accounts.spotify.com/api/token'
    token_data = {
        'grant_type': 'refresh_token',
        'refresh_token': refresh_token
    }
    token_headers = {
        'Authorization': f'Basic {base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()}',
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    response = requests.post(token_url, data=token_data, headers=token_headers)
    if response.status_code == 200:
        new_tokens = response.json()
        update_token_storage(new_tokens)
        print("Spotify access token refreshed successfully.")
        return fetch_current_track()  # Retry with new access token
    else:
        print(f"Error refreshing token: {response.status_code} {response.text}")
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
        if response.status_code == 204:
            return None  # No content playing
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

def display_clock_on_matrix(font_size=20, font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
    """Displays the current time (hours and minutes) on the LED matrix with adjustable font size."""
    global matrix

    # Create a blank image
    clock_image = Image.new('RGB', (matrix.width, matrix.height), (0, 0, 0))
    draw = ImageDraw.Draw(clock_image)

    # Get the current time
    current_time = datetime.now().strftime('%H:%M')

    # Load the font with the specified size
    try:
        # Load a TrueType font from the specified path with the given size
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Error loading font '{font_path}'. Falling back to default font.")
        font = ImageFont.load_default()  # Fallback to default font if TrueType font is not found

    # Calculate text size and position
    text_width, text_height = draw.textsize(current_time, font=font)
    position = ((matrix.width - text_width) // 2, (matrix.height - text_height) // 2)

    # Draw the clock text on the image
    draw.text(position, current_time, font=font, fill=(255, 255, 255))

    # Display the clock image on the matrix
    with matrix_lock:
        matrix.SetImage(clock_image.convert('RGB'))
        print("Clock displayed")

# Example usage:
display_clock_on_matrix(font_size=20)  # Uses DejaVuSans-Bold with size 20


def main():
    global previous_poster_url, previous_album_art_url, previous_watching_state

    setup_matrix()
    # Initialize token storage with some default values or load from an initial source
    update_token_storage({
        'access_token': "BQCCCam7Pm4qeJYnAIuaDBZD86CaIzAADEDJ7GCEXJfCKzTk5wyxoOPYlN_HvFE0I54AdJNIl7m9S3oWXpMEQcL54LhLFVpkk6xBKKuxAn_e5b93GLojfLhPT8uRUMdmd5RryH-zgm8OKa6GgelDLdjznCWNp_mHzpBzOt1XYkT4iPA8UE4SiOGcFWM1SXyGPYVUz50M15SGEjxVVug",
        'refresh_token': "AQAK9lLvojbE2p89VdwNu32mJA8voVCTMNy2bX24tw7txev4sE6C4tVARqBzBbqbKqp0mwRcAwCp6RfiMHW7sfRdd5Zl3R9iz96jHCGaVvnqtl3IHWtVRusq8WDAv7oe7W0",
        'client_id': "95e5ef96fe61488bacb034177158dfab",
        'client_secret': "2bb55f0d1dbf4b23b465e0ea28c90f7e"
    })

    while True:
        # Fetch data from both sources
        track_data = fetch_current_track()
        watching_data = fetch_currently_watching()

        # Determine if anything is playing
        track_is_playing = track_data and 'item' in track_data and track_data.get('is_playing', False)
        watching_is_playing = watching_data and 'type' in watching_data

        if track_is_playing:
            album_art_url = track_data['item']['album']['images'][0]['url']
            print(f"Currently playing track: {track_data['item']['name']}")
            display_album_art(album_art_url)
            poster_url = None
        else:
            album_art_url = None

        if watching_is_playing:
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
            poster_url = None

        # Display clock if nothing is playing
        if album_art_url is None and poster_url is None:
            if previous_watching_state != 'clock':
                display_clock_on_matrix(font-size=20)  # Display the clock
                previous_watching_state = 'clock'
        else:
            previous_watching_state = 'content'  # Update watching state if content is playing

        # Sleep before the next check
        time.sleep(10)

if __name__ == '__main__':
    main()
