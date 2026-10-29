from flask import Flask, render_template, request, jsonify
import os

app = Flask(__name__, static_folder='static', template_folder='templates')
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/detect', methods=['POST'])
def detect():
    if 'file' not in request.files:
        return jsonify({'error': 'No file uploaded'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400
    
    file_path = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(file_path)
    
    # Placeholder for deepfake detection logic
    is_deepfake = False 
    confidence = 0.85
    
    return jsonify({
        'filename': file.filename,
        'is_deepfake': is_deepfake,
        'confidence': confidence
    })

if __name__ == '__main__':
    app.run(debug=True)
