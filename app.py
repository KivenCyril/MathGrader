import os
import sys
import json
from pathlib import Path
from flask import Flask, jsonify, request, send_from_directory
from flask_cors import CORS

# Ensure src is in python path
sys.path.append(str(Path(__file__).parent))

try:
    from src.datasets.math23k import load_math23k
except ImportError:
    # Fallback if running from a different directory context
    sys.path.append(os.getcwd())
    from src.datasets.math23k import load_math23k

app = Flask(__name__, static_folder='front')
CORS(app) # Allow cross-origin for local dev if needed


DATA_ROOT = Path("data/raw")

@app.route('/')
def index():
    return send_from_directory('front', 'test.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('front', path)

@app.route('/api/datasets')
def list_datasets():
    datasets = []
    # Walk through data/raw to find json files
    if DATA_ROOT.exists():
        for root, dirs, files in os.walk(DATA_ROOT):
            for file in files:
                if file.endswith('.json'):
                    # Create a relative path ID
                    rel_path = os.path.relpath(os.path.join(root, file), DATA_ROOT)
                    datasets.append({
                        "id": rel_path.replace("\\", "/"),
                        "name": file,
                        "group": os.path.basename(root)
                    })
    return jsonify(datasets)

@app.route('/api/load')
def load_dataset():
    dataset_id = request.args.get('id')
    if not dataset_id:
        return jsonify({"error": "Missing id parameter"}), 400
    
    file_path = DATA_ROOT / dataset_id
    if not file_path.exists():
        return jsonify({"error": "Dataset not found"}), 404
    
    # Check which loader to use based on file/folder
    # For now, we assume everything is math23k format or similar enough
    # The user only asked to optimize the interface, so using the existing loader is a good start.
    try:
        # We use the load_math23k function we saw earlier
        # It returns List[MathProblem] objects. We need to convert them to dicts.
        problems = load_math23k(file_path)
        
        # Convert to the format expected by the frontend
        # Frontend expects: { id, text, truth, meta, maxScore }
        result = []
        for p in problems:
            result.append({
                "id": p.id,
                "text": p.question,
                "truth": p.answer,
                "meta": f"{p.source} (Eq: {p.equation})",
                "maxScore": 1
            })
            
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    print("Starting server at http://localhost:5000")
    app.run(debug=True, port=5000)
