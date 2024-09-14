import requests
import json
from PIL import Image, ImageDraw, ImageFont
from io import BytesIO
import time
from rgbmatrix import RGBMatrix, RGBMatrixOptions
from threading import Lock
import base64

# In-memory token storage
token_storage = {
    'access_token': "BQCCCam7Pm4qeJYnAIuaDBZD86CaIzAADEDJ7GCEXJfCKzTk5wyxoOPYlN_HvFE0I54AdJNIl7m9S3oWXpMEQcL54LhLFVpkk6xBKKuxAn_e5b93GLojfLhPT8uRUMdmd5RryH-zgm8OKa6GgelDLdjznCWNp_mHzpBzOt1XYkT4iPA8UE4SiOGcFWM1SXyGPYVUz50M15SGEjxVVug",
    'refresh_token': "AQAK9lLvojbE2p89VdwNu32mJA8voVCTMNy2bX24tw7txev4sE6C4tVARqBzBbqbKqp0mwRcAwCp6RfiMHW7sfRdd5Zl3R9iz96jHCGaVvnqtl3IHWtVRusq8WDAv7oe7W0",
    'client_id': "95e5ef96fe61488bacb034177158dfab",
    'client_secret': "2bb55f0d1dbf4b23b465e0ea28c90f7e"
}

# Load configuration
with open('config.json') as config_file:
    config = json.load(config_file)

client_id = config['client_id']
tmdb_api_key = config['tmdb_api_key']
trakt_username = config['trakt_username']

# Headers for Trakt API
trakt_headers = {
    'Content-Type': 'application/json',
    'trakt-api-key': client_id,
    'trakt-api-version': '2',
}

matrix = None
fill_image = True
zoom_percentage = 0
offset_pixels = 0
clock_overlay = True

# Create a lock for the matrix
matrix_lock = Lock()

def setup_matrix():
    global matrix
    options = RGBMatrixOptions()
    options.rows = 64
    options.cols = 64
    options.chain_length = 1
    options.parallel = 1
    options.hardware_mapping = 'adafruit-hat-pwm'
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
        data = response.json()
        print("Currently watching data:", data)  # Debugging output
        return data
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

def resize_image(image, target_size, fill_matrix=True, zoom_percentage=0, offset_pixels=0, is_poster=False):
    img_width, img_height = image.size
    target_width, target_height = target_size

    img_aspect = img_width / img_height
    target_aspect = target_width / target_height

    if is_poster:
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
    else:
        # Resize for non-poster images, if needed
        img = image.resize((target_width, target_height), Image.LANCZOS)

    return img

def calculate_brightness(image):
    """Calculate the average brightness of the image."""
    grayscale_image = image.convert('L')
    pixels = list(grayscale_image.getdata())
    avg_brightness = sum(pixels) / len(pixels)
    return avg_brightness

def draw_clock_on_image(image):
    """Draw the clock on the provided image, ensuring it is centered."""
    draw = ImageDraw.Draw(image)
    font_size = 18
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    
    current_time = time.strftime('%H:%M')
    
    try:
        font = ImageFont.truetype(font_path, font_size)
    except IOError:
        print(f"Error loading font '{font_path}'. Falling back to default font.")
        font = ImageFont.load_default()

    # Calculate text size using textbbox
    text_bbox = draw.textbbox((0, 0), current_time, font=font)
    text_width = text_bbox[2] - text_bbox[0]
    text_height = text_bbox[3] - text_bbox[1]
    
    # Center the text horizontally and vertically, with a manual vertical adjustment
    position_x = (image.width - text_width) // 2
    position_y = (image.height - text_height) // 2 - 4  # Adjust this offset to fine-tune vertical centering

    # Determine text color and outline color based on average brightness
    avg_brightness = calculate_brightness(image)
    text_color = (0, 0, 0) if avg_brightness > 255 else (255, 255, 255)
    outline_color = (255, 255, 255) if text_color == (0, 0, 0) else (0, 0, 0)

    # Draw the text with an outline
    draw.text(
        (position_x, position_y),
        current_time,
        font=font,
        fill=text_color,
        stroke_width=2,        # Width of the outline
        stroke_fill=outline_color # Color of the outline
    )
    
    return image


def display_image_on_matrix(image, draw_clock=False):
    image = image.convert('RGB')
    image = resize_image(image, (matrix.width, matrix.height), fill_image, zoom_percentage, offset_pixels, is_poster=True)
    
    if draw_clock:
        image = draw_clock_on_image(image)

    with matrix_lock:
        matrix.SetImage(image)

def display_watching_info(watching_data):
    image_url = None
    if watching_data['type'] == 'movie':
        image_url = fetch_poster_from_tmdb(watching_data['movie']['ids']['tmdb'])
    elif watching_data['type'] == 'episode':
        image_url = fetch_poster_from_tmdb(
            watching_data['show']['ids']['tmdb'],
            is_movie=False,
            season_number=watching_data['episode']['season']
        )

    if image_url:
        image = fetch_album_artwork(image_url)
        if image:
            display_image_on_matrix(image, draw_clock=clock_overlay)

def main_loop():
    global fill_image, zoom_percentage, offset_pixels, clock_overlay

    setup_matrix()
    previous_watching_state = 'clock'
    last_minute = time.strftime('%H:%M')

    while True:
        track_data = fetch_current_track()
        watching_data = fetch_currently_watching()

        track_is_playing = track_data and 'item' in track_data and track_data.get('is_playing', False)
        watching_is_playing = watching_data and 'type' in watching_data

        is_playing_content = track_is_playing or watching_is_playing

        if is_playing_content:
            previous_watching_state = 'content'
            if track_is_playing:
                album_art_url = track_data.get('item', {}).get('album', {}).get('images', [{}])[0].get('url')
                if album_art_url:
                    image = fetch_album_artwork(album_art_url)
                    if image:
                        display_image_on_matrix(image, draw_clock=clock_overlay)
            elif watching_is_playing:
                display_watching_info(watching_data)
        else:
            current_minute = time.strftime('%H:%M')
            if previous_watching_state != 'clock' or last_minute != current_minute:
                clock_image = Image.new('RGB', (matrix.width, matrix.height), (0, 0, 0))
                clock_image = draw_clock_on_image(clock_image)
                with matrix_lock:
                    matrix.SetImage(clock_image.convert('RGB'))
                    print("Clock displayed")
                last_minute = current_minute
            previous_watching_state = 'clock'

        time.sleep(10)  # Delay between updates
      
if __name__ == "__main__":
    main_loop()
