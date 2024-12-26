from flask import Flask, request, jsonify, send_from_directory, render_template
from apscheduler.schedulers.background import BackgroundScheduler
from PIL import Image
import os
import threading
import uuid
import datetime
import shutil
import math

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads/'
PROCESSED_FOLDER = 'processed/'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
if not os.path.exists(PROCESSED_FOLDER):
    os.makedirs(PROCESSED_FOLDER)

tasks = {}

def calculate_entropy_map(image, kernel_size=3):
    """Calculates the entropy map of the image."""
    width, height = image.size
    entropy_map = [[0 for _ in range(width)] for _ in range(height)]
    for y in range(height):
        for x in range(width):
            local_histogram = [0] * 256
            for ky in range(-kernel_size // 2, kernel_size // 2 + 1):
                for kx in range(-kernel_size // 2, kernel_size // 2 + 1):
                    new_x = (x + kx) % width
                    new_y = (y + ky) % height
                    pixel_value = image.getpixel((new_x, new_y))
                    grayscale_value = int(0.21 * pixel_value[0] + 0.72 * pixel_value[1] + 0.07 * pixel_value[2])
                    local_histogram[grayscale_value] += 1
            entropy_map[y][x] = calculate_entropy(local_histogram)
    return entropy_map

def calculate_entropy(histogram):
    """Calculates the Shannon entropy of a histogram."""
    total_pixels = sum(histogram)
    entropy = 0
    for count in histogram:
        if count > 0:
            probability = count / total_pixels
            entropy -= probability * math.log2(probability)
    return entropy

def modify_image_based_on_entropy(image, entropy_map):
    """Modifies the image based on the entropy map."""
    width, height = image.size
    modified_image = Image.new(image.mode, image.size)
    for y in range(height):
        for x in range(width):
            current_pixel_value = image.getpixel((x, y))
            entropy = entropy_map[y][x]
            new_pixel_value = tuple([(channel + int(entropy * 10)) % 256 for channel in current_pixel_value])
            modified_image.putpixel((x, y), new_pixel_value)
    return modified_image

@app.route('/', methods=['GET'])
def index():
    return render_template('upload.html')

@app.route('/upload', methods=['POST'])
def upload_image():
    file = request.files['file']
    if file and file.filename.endswith(('.png', '.jpg', '.jpeg')):
        unique_id = str(uuid.uuid4())
        filepath = os.path.join(UPLOAD_FOLDER, unique_id + os.path.splitext(file.filename)[1])
        file.save(filepath)
        tasks[unique_id] = {'status': 'processing'}
        thread = threading.Thread(target=process_image, args=(filepath, unique_id))
        thread.start()
        return jsonify({'image_id': unique_id}), 202
    else:
        return jsonify({'error': 'Invalid file format'}), 400

def process_image(filepath, image_id):
    image = Image.open(filepath)
    entropy_map = calculate_entropy_map(image)
    modified_image = modify_image_based_on_entropy(image, entropy_map)
    processed_path = os.path.join(PROCESSED_FOLDER, f"{image_id}_modified.png")
    modified_image.save(processed_path)
    tasks[image_id] = {'status': 'done', 'path': processed_path, 'entropy_avg': sum(sum(row) for row in entropy_map) / (len(entropy_map) * len(entropy_map[0]))}

@app.route('/status/<image_id>')
def status(image_id):
    return jsonify(tasks.get(image_id, {'status': 'unknown'}))

@app.route('/download/<image_id>')
def download(image_id):
    file_info = tasks.get(image_id, {})
    if 'path' in file_info:
        return send_from_directory(os.path.dirname(file_info['path']), os.path.basename(file_info['path']), as_attachment=True)
    return 'File not found', 404

@app.route('/getavg/<image_id>')
def get_avg(image_id):
    file_info = tasks.get(image_id, {})
    if 'entropy_avg' in file_info:
        return jsonify({'entropy_avg': file_info['entropy_avg']})
    return jsonify({'error': 'Entropy average not found'}), 404

def cleanup_directory(path, max_age_minutes=1):
    """Remove files older than `max_age_hours` from the specified directory."""
    for filename in os.listdir(path):
        file_path = os.path.join(path, filename)
        if os.stat(file_path).st_mtime < datetime.datetime.now().timestamp() - max_age_minutes * 60:
            os.remove(file_path)
            
            print(f"Removed {file_path}")

def schedule_cleanup():
    """Schedule cleanup tasks for upload and processed directories."""
    scheduler = BackgroundScheduler()
    scheduler.add_job(cleanup_directory, 'interval', hours=1, args=[UPLOAD_FOLDER])
    scheduler.add_job(cleanup_directory, 'interval', hours=1, args=[PROCESSED_FOLDER])
    scheduler.start()

@app.after_request
def initialize_scheduler(respone):
    schedule_cleanup()
    return respone

@app.route('/howitworks', methods=['GET'])
def howitworks():
    return render_template('howitworks.html')


@app.route('/images/<filename>')
def custom_static(filename):
    return send_from_directory('images', filename)

if __name__ == '__main__':
    app.run(debug=False)
