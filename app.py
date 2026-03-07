import os
import json
import subprocess
import uuid
import datetime
import logging
from flask import Flask, render_template, request, jsonify, send_file, after_this_request
import pygame
from io import BytesIO
import zipfile

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'generated'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize pygame mixer
pygame.mixer.init()

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

def get_default_values():
    return {
        "caption": "",
        "lyrics": "[instrumental]",
        "duration": 0,
        "lm_negative_prompt": "",
        "bpm": 0,
        "keyscale": "",
        "timesignature": "",
        "vocal_language": "en",
        "seed": -1,
        "lm_temperature": 0.85,
        "lm_cfg_scale": 2.0,
        "lm_top_p": 0.9,
        "lm_top_k": 0,
        "audio_codes": "",
        "inference_steps": 8,
        "guidance_scale": 0.0,
        "shift": 3.0,
        "audio_cover_strength": 0.5
    }

def generate_filename():
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"music_gen_{timestamp}"

def run_command(cmd, cwd=None):
    try:
        logger.info(f"Executing command: {cmd}")
        result = subprocess.run(
            cmd, 
            shell=True, 
            check=True, 
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd
        )
        logger.info(f"Command output: {result.stdout}")
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        error_msg = f"Command failed: {e.stderr}"
        logger.error(error_msg)
        return False, error_msg

def cleanup_files(base_filename, use_llm=False):
    if not base_filename:
        return
    
    files_to_remove = [f"{base_filename}.json"]
    
    # For LLM generations, we have an intermediate JSON and double-zero WAV
    if use_llm:
        files_to_remove.extend([
            f"{base_filename}0.json",  # Intermediate JSON
            f"{base_filename}00.wav"   # Output WAV for LLM
        ])
    # For non-LLM generations, we have a single-zero WAV
    else:
        files_to_remove.append(f"{base_filename}0.wav")  # Output WAV for non-LLM
    
    for file in files_to_remove:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Removed file: {file_path}")
        except Exception as e:
            logger.error(f"Error removing file {file_path}: {str(e)}")

@app.route('/')
def index():
    return render_template('index.html', defaults=get_default_values())

@app.route('/generate', methods=['POST'])
def generate():
    base_filename = None
    use_llm = False
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                "status": "error",
                "message": "No data received in request"
            }), 400

        use_llm = data.get('use_llm', False)
        logger.info(f"Received generation request with use_llm={use_llm}")
        
        # Generate unique filename
        base_filename = generate_filename()
        json_filename = f"{base_filename}.json"
        json_path = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)
        
        # Prepare data for JSON
        json_data = {
            "caption": data.get("caption", ""),
            "lyrics": data.get("lyrics", "[instrumental]"),
            "bpm": data.get("bpm", 0),
            "duration": data.get("duration", 0),
            "keyscale": data.get("keyscale", ""),
            "timesignature": data.get("timesignature", ""),
            "vocal_language": data.get("vocal_language", "en"),
            "seed": data.get("seed", -1),
            "lm_temperature": data.get("lm_temperature", 0.85),
            "lm_cfg_scale": data.get("lm_cfg_scale", 2.0),
            "lm_top_p": data.get("lm_top_p", 0.9),
            "lm_top_k": data.get("lm_top_k", 0),
            "lm_negative_prompt": data.get("lm_negative_prompt", ""),
            "audio_codes": data.get("audio_codes", ""),
            "inference_steps": data.get("inference_steps", 8),
            "guidance_scale": data.get("guidance_scale", 0.0),
            "shift": data.get("shift", 3.0),
            "audio_cover_strength": data.get("audio_cover_strength", 0.5)
        }
        
        # Save JSON file
        with open(json_path, 'w') as f:
            json.dump(json_data, f, indent=2)
            logger.info(f"Saved JSON configuration to {json_path}")
        
        # Run commands based on LLM selection
        success = False
        output = ""
        
        if use_llm:
            logger.info("Running with LLM pipeline")
            # First command
            cmd1 = f"./bin/ace-qwen3 --request {json_path} --model ./models/acestep-5Hz-lm-4B-Q8_0.gguf"
            success, output = run_command(cmd1)
            
            if not success:
                logger.error(f"LLM generation failed: {output}")
                cleanup_files(base_filename, use_llm)
                return jsonify({
                    "status": "error", 
                    "message": f"LLM generation failed: {output}",
                    "details": "Check if the ace-qwen3 executable and model files are in the correct location."
                })
            
            # Second command
            intermediate_json = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_filename}0.json")
            if not os.path.exists(intermediate_json):
                error_msg = f"Intermediate JSON file not found: {intermediate_json}"
                logger.error(error_msg)
                return jsonify({
                    "status": "error",
                    "message": "LLM generation completed but intermediate file was not created",
                    "details": error_msg
                })
            
            cmd2 = f"./bin/dit-vae --request {intermediate_json} --text-encoder ./models/Qwen3-Embedding-0.6B-Q8_0.gguf --dit ./models/acestep-v15-turbo-Q8_0.gguf --vae ./models/vae-BF16.gguf"
            success, output = run_command(cmd2)
            
            if success:
                # When using LLM, the output file will have two zeros: {base_filename}00.wav
                wav_filename = f"{base_filename}00.wav"
                wav_path = os.path.join(app.config['UPLOAD_FOLDER'], wav_filename)
                
                if os.path.exists(wav_path):
                    logger.info(f"Successfully generated audio with LLM at {wav_path}")
                    return jsonify({
                        "status": "success",
                        "base_filename": base_filename,
                        "wav_url": f"/preview/{wav_filename}",
                        "download_url": f"/download/{base_filename}",
                        "use_llm": True
                    })
        else:
            logger.info("Running without LLM pipeline")
            cmd = f"./bin/dit-vae --request {json_path} --text-encoder ./models/Qwen3-Embedding-0.6B-Q8_0.gguf --dit ./models/acestep-v15-turbo-Q8_0.gguf --vae ./models/vae-BF16.gguf"
            success, output = run_command(cmd)
            
            if success:
                # Without LLM, the output file has one zero: {base_filename}0.wav
                wav_filename = f"{base_filename}0.wav"
                wav_path = os.path.join(app.config['UPLOAD_FOLDER'], wav_filename)
                
                if os.path.exists(wav_path):
                    logger.info(f"Successfully generated audio without LLM at {wav_path}")
                    return jsonify({
                        "status": "success",
                        "base_filename": base_filename,
                        "wav_url": f"/preview/{wav_filename}",
                        "download_url": f"/download/{base_filename}",
                        "use_llm": False
                    })
        
        # If we get here, the command failed
        logger.error(f"Command failed: {output}")
        return jsonify({
            "status": "error",
            "message": "Audio generation failed",
            "details": output
        })
        
    except Exception as e:
        error_msg = f"Unexpected error: {str(e)}"
        logger.exception(error_msg)
        return jsonify({
            "status": "error",
            "message": "An unexpected error occurred",
            "details": error_msg
        })
    finally:
        # Ensure cleanup happens even if there's an error
        if not success and base_filename:
            cleanup_files(base_filename, use_llm)

@app.route('/preview/<filename>')
def preview(filename):
    wav_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if not os.path.exists(wav_path):
        return jsonify({"status": "error", "message": "File not found"}), 404
    return send_file(wav_path, mimetype='audio/wav')

@app.route('/download/<base_filename>')
def download(base_filename):
    # Check if the request includes LLM flag
    use_llm = request.args.get('use_llm', 'false').lower() == 'true'
    zip_filename = f"{base_filename}.zip"
    zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)
    
    # Define files to include based on whether LLM was used
    files_to_zip = [f"{base_filename}.json"]  # Always include the main JSON
    
    if use_llm:
        # For LLM generations, include intermediate JSON and double-zero WAV
        files_to_zip.extend([
            f"{base_filename}0.json",  # Intermediate JSON
            f"{base_filename}00.wav"   # Output WAV
        ])
    else:
        # For non-LLM generations, only include the single-zero WAV
        files_to_zip.append(f"{base_filename}0.wav")  # Output WAV
    
    # Check which files actually exist
    existing_files = []
    missing_files = []
    
    for file in files_to_zip:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
        if os.path.exists(file_path):
            existing_files.append(file)
        else:
            missing_files.append(file)
    
    # If any required files are missing, return an error
    if missing_files:
        error_msg = f"Missing files: {', '.join(missing_files)}"
        logger.error(error_msg)
        return jsonify({
            "status": "error",
            "message": "Could not create download package",
            "details": error_msg
        }), 404
    
    # Create ZIP file
    try:
        with zipfile.ZipFile(zip_path, 'w') as zipf:
            for file in existing_files:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)
                zipf.write(file_path, arcname=file)
    except Exception as e:
        error_msg = f"Error creating ZIP file: {str(e)}"
        logger.error(error_msg)
        return jsonify({
            "status": "error",
            "message": "Could not create download package",
            "details": error_msg
        }), 500
    
    # Cleanup after sending the file
    @after_this_request
    def remove_file(response):
        try:
            # Remove ZIP file
            if os.path.exists(zip_path):
                os.remove(zip_path)
                logger.info(f"Removed ZIP file: {zip_path}")
            # Remove original files
            cleanup_files(base_filename, use_llm)
        except Exception as e:
            logger.error(f"Error removing files: {e}")
        return response
    
    return send_file(zip_path, as_attachment=True, download_name=zip_filename)

if __name__ == '__main__':
    app.run(debug=True, port=5000)