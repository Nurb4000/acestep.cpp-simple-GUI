import os  
import json  
import subprocess  
import uuid  
import datetime  
import logging  
import sys  
from flask import Flask, render_template, request, jsonify, send_file, after_this_request  
import flask  # Added for version detection  
from io import BytesIO  
import zipfile  
  
# Initialize Flask app  
app = Flask(__name__)  
app.config['UPLOAD_FOLDER'] = 'generated'  
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size  
  
# Configure logging  
logging.basicConfig(level=logging.DEBUG)  
logger = logging.getLogger(__name__)  
  
# Check for oldGPU parameter  
use_old_gpu = any(arg.lower() == 'oldgpu=1' for arg in sys.argv[1:])  
if use_old_gpu:  
    logger.info("Old GPU mode enabled - will add --clamp-fp16 to commands")  
  
# Ensure upload folder exists  
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)  
  
# Model inference steps mapping
MODEL_INFERENCE_STEPS = {
    "./models/acestep-v15-turbo-Q8_0.gguf": 8,
    "./models/acestep-v15-sft-Q8_0.gguf": 30,
    "./models/acestep-v15-base-Q8_0.gguf": 50
}
  
  
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
        "audio_cover_strength": 0.5,
        "dit_model": "./models/acestep-v15-turbo-Q8_0.gguf"  # Default model
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
  

def cleanup_files(base_filename, use_llm=False, reference_audio_filename=None):  
    if not base_filename:  
        logger.info("No base filename provided for cleanup")  
        return  
    files_to_remove = [f"{base_filename}.json"]  
    if use_llm:  
        files_to_remove.extend([  
            f"{base_filename}0.json",  
            f"{base_filename}00.wav"  
        ])  
    else:  
        files_to_remove.append(f"{base_filename}0.wav")  
   
    # Clean up reference audio file if provided  
    if reference_audio_filename:  
        ref_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], reference_audio_filename)  
        if os.path.exists(ref_audio_path):  
            try:  
                os.remove(ref_audio_path)  
                logger.info(f"Removed reference audio file: {ref_audio_path}")  
            except Exception as e:  
                logger.error(f"Error removing reference audio file {ref_audio_path}: {str(e)}")  
   
    # Clean up LLM generated files if they exist  
    llm_json = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_filename}0.json")  
    if os.path.exists(llm_json):  
        try:  
            os.remove(llm_json)  
            logger.info(f"Removed LLM JSON file: {llm_json}")  
        except Exception as e:  
            logger.error(f"Error removing LLM JSON file {llm_json}: {str(e)}")  
   
    for file in files_to_remove:  
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], file)  
        try:  
            if os.path.exists(file_path):  
                os.remove(file_path)  
                logger.info(f"Removed file: {file_path}")  
        except Exception as e:  
            logger.error(f"Error removing file {file_path}: {str(e)}")  
   
  
def get_flask_version():  
    """Get Flask version and return as tuple of integers (major, minor)"""  
    version_str = flask.__version__  
    # Handle version strings like '2.0.1' or '2.1.dev0'  
    version_parts = []  
    for part in version_str.split('.')[:2]:  # Only care about major and minor  
        # Remove any non-numeric suffix  
        numeric_part = ''  
        for char in part:  
            if char.isdigit():  
                numeric_part += char  
            else:  
                break  
        version_parts.append(int(numeric_part) if numeric_part else 0)  
    return tuple(version_parts)  
   
   
@app.route('/')  
def index():  
    return render_template('index.html', defaults=get_default_values())  
   
   
@app.route('/generate', methods=['POST'])  
def generate():  
    base_filename = None  
    use_llm = False  
    reference_audio_filename = None  
    success = False  
    try:  
        # DEBUG: Log all form data and files received  
        logger.debug(f"Request form data: {dict(request.form)}")  
        logger.debug(f"Request files keys: {list(request.files.keys())}")  
        logger.debug(f"Request content-type: {request.content_type}")  
         
        # Check if 'reference_audio' file is present in request.files  
        has_file_upload = 'reference_audio' in request.files and request.files['reference_audio'].filename != ''  
        logger.info(f"File upload detected: {has_file_upload}")  
         
        # Parse flags from form  
        use_llm = request.form.get('use_llm', 'false').lower() == 'true'  
        enhance_via_llm = request.form.get('enhance_via_llm', 'false').lower() == 'true'  
        use_reference_audio = request.form.get('use_reference_audio', 'false').lower() == 'true'  
        logger.info(f"Received generation request with use_llm={use_llm}, enhance_via_llm={enhance_via_llm}, use_reference_audio={use_reference_audio}")  
         
        # Get selected DIT model
        dit_model = request.form.get('dit_model', './models/acestep-v15-turbo-Q8_0.gguf')
        # Validate model path
        if dit_model not in MODEL_INFERENCE_STEPS:
            dit_model = './models/acestep-v15-turbo-Q8_0.gguf'
        
        # Get inference steps from form data
        inference_steps = int(request.form.get('inference_steps', 8))
        
        # Generate unique filename  
        base_filename = generate_filename()  
        json_filename = f"{base_filename}.json"  
        json_path = os.path.join(app.config['UPLOAD_FOLDER'], json_filename)  
         
        # Handle reference audio file upload  
        if use_reference_audio and has_file_upload:  
            ref_file = request.files['reference_audio']  
            logger.info(f"Reference file info: filename={ref_file.filename}, content_type={ref_file.content_type}")  
            if ref_file.filename == '':  
                return jsonify({  
                    "status": "error",  
                    "message": "No reference audio selected"  
                }), 400  
     
            # Generate unique filename for reference audio  
            ext = os.path.splitext(ref_file.filename)[1] or '.wav'  
            reference_audio_filename = f"{base_filename}_ref{ext}"  
            ref_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], reference_audio_filename)  
            try:  
                ref_file.save(ref_audio_path)  
                logger.info(f"Saved reference audio to {ref_audio_path}")  
                # Verify file was saved  
                if not os.path.exists(ref_audio_path):  
                    raise Exception("File was not created after save")  
                file_size = os.path.getsize(ref_audio_path)  
                logger.info(f"Reference audio saved successfully, size: {file_size} bytes")  
            except Exception as e:  
                logger.error(f"Error saving reference audio: {str(e)}")  
                return jsonify({  
                    "status": "error",  
                    "message": "Failed to save reference audio file"  
                }), 500  
         
        # Prepare JSON data  
        json_data = {  
            "caption": request.form.get("caption", ""),  
            "lyrics": request.form.get("lyrics", "[instrumental]"),  
            "bpm": float(request.form.get("bpm", 0)) if request.form.get("bpm") else 0,  
            "duration": float(request.form.get("duration", 0)) if request.form.get("duration") else 0,  
            "keyscale": request.form.get("keyscale", ""),  
            "timesignature": request.form.get("timesignature", ""),  
            "vocal_language": request.form.get("vocal_language", "en"),  
            "seed": int(request.form.get("seed", -1)) if request.form.get("seed") else -1,  
            "lm_temperature": float(request.form.get("lm_temperature", 0.85)),  
            "lm_cfg_scale": float(request.form.get("lm_cfg_scale", 2.0)),  
            "lm_top_p": float(request.form.get("lm_top_p", 0.9)),  
            "lm_top_k": int(request.form.get("lm_top_k", 0)) if request.form.get("lm_top_k") else 0,  
            "lm_negative_prompt": request.form.get("lm_negative_prompt", ""),  
            "audio_codes": request.form.get("audio_codes", ""),  
            "inference_steps": inference_steps,  # Use the value from the form
            "guidance_scale": float(request.form.get("guidance_scale", 0.0)),  
            "shift": float(request.form.get("shift", 3.0)),  
            "audio_cover_strength": float(request.form.get("audio_cover_strength", 0.5)),
            "dit_model": dit_model  # Store selected model
        }  
         
        # Save JSON file  
        with open(json_path, 'w') as f:  
            json.dump(json_data, f, indent=2)  
        logger.info(f"Saved JSON configuration to {json_path}")  
         
        # Handle LLM enhancement (only when enhance_via_llm is true)  
        if enhance_via_llm:  
            logger.info("Running LLM enhancement")  
     
            # First command: LLM generation  
            cmd1 = f"./bin/ace-lm --request {json_path} --lm ./models/acestep-5Hz-lm-4B-Q8_0.gguf"  
            if use_old_gpu:  
                cmd1 += " --clamp-fp16"  
                logger.info("Adding --clamp-fp16 for old GPU support")  
     
            success, output = run_command(cmd1)  
            if not success:  
                logger.error(f"LLM enhancement failed: {output}")  
                cleanup_files(base_filename, use_llm, reference_audio_filename)  
                return jsonify({  
                    "status": "error",  
                    "message": f"LLM enhancement failed: {output}",  
                    "details": "Check if the ace-lm executable and model files are in the correct location."  
                })  
     
            # Check intermediate JSON  
            intermediate_json = os.path.join(app.config['UPLOAD_FOLDER'], f"{base_filename}0.json")  
            if not os.path.exists(intermediate_json):  
                error_msg = f"Intermediate JSON file not found: {intermediate_json}"  
                logger.error(error_msg)  
                return jsonify({  
                    "status": "error",  
                    "message": "LLM enhancement completed but intermediate file was not created",  
                    "details": error_msg  
                })  
     
            # Read the enhanced JSON data with encoding handling  
            try:  
                with open(intermediate_json, 'r', encoding='utf-8') as f:  
                    enhanced_data = json.load(f)  
            except UnicodeDecodeError as e:  
                logger.error(f"Failed to decode intermediate JSON file {intermediate_json}: {e}")  
                return jsonify({  
                    "status": "error",  
                    "message": "Failed to read LLM-enhanced data due to encoding issue",  
                    "details": str(e)  
                })  
            except json.JSONDecodeError as e:  
                logger.error(f"Invalid JSON in intermediate file {intermediate_json}: {e}")  
                return jsonify({  
                    "status": "error",  
                    "message": "Invalid JSON in LLM-enhanced data",  
                    "details": str(e)  
                })  
     
            # Return enhanced data for GUI update  
            return jsonify({  
                "status": "enhanced",  
                "enhanced_data": enhanced_data,  
                "base_filename": base_filename,  
                "use_llm": False,  # Always false for enhancement  
                "use_reference_audio": use_reference_audio  
            })  
     
        # Regular generation (without LLM)  
        logger.info("Running without LLM pipeline")  
        # Use the selected DIT model in the command
        cmd = f"./bin/ace-synth --request {json_path} --embedding ./models/Qwen3-Embedding-0.6B-Q8_0.gguf --dit {dit_model} --vae ./models/vae-BF16.gguf --wav"  
        if use_old_gpu:  
            cmd += " --clamp-fp16"  
            logger.info("Adding --clamp-fp16 for old GPU support")  
     
        if use_reference_audio and reference_audio_filename:  
            ref_audio_path = os.path.join(app.config['UPLOAD_FOLDER'], reference_audio_filename)  
            cmd = f"./bin/ace-synth --src-audio {ref_audio_path} --request {json_path} --embedding ./models/Qwen3-Embedding-0.6B-Q8_0.gguf --dit {dit_model} --vae ./models/vae-BF16.gguf --wav"  
            if use_old_gpu:  
                cmd += " --clamp-fp16"  
                logger.info("Adding --clamp-fp16 for old GPU support (with reference audio)")  
     
        logger.info(f"Final command: {cmd}")  
        success, output = run_command(cmd)  
        if success:  
            wav_filename = f"{base_filename}0.wav"  
            wav_path = os.path.join(app.config['UPLOAD_FOLDER'], wav_filename)  
            if os.path.exists(wav_path):  
                logger.info(f"Successfully generated audio without LLM at {wav_path}")  
                return jsonify({  
                    "status": "success",  
                    "base_filename": base_filename,  
                    "wav_url": f"/preview/{wav_filename}",  
                    "download_url": f"/download/{base_filename}",  
                    "use_llm": False,  # Always false for regular generation  
                    "use_reference_audio": use_reference_audio  
                })  
     
        # If we get here, command failed  
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
        }), 500   
   
    finally:  
        if not success and base_filename:  
            cleanup_files(base_filename, use_llm, reference_audio_filename)  
   
   
@app.route('/preview/<filename>')  
def preview(filename):  
    wav_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)  
    if not os.path.exists(wav_path):  
        return jsonify({"status": "error", "message": "File not found"}), 404  
    return send_file(wav_path, mimetype='audio/wav')  
   
   
@app.route('/download/<base_filename>')  
def download(base_filename):  
    # Check if the request includes LLM and reference audio flags  
    use_llm = request.args.get('use_llm', 'false').lower() == 'true'  
    use_reference_audio = request.args.get('use_reference_audio', 'false').lower() == 'true'  
    zip_filename = f"{base_filename}.zip"  
    zip_path = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)  
   
    # Define files to include based on whether LLM was used  
    files_to_zip = [f"{base_filename}.json"]  # Always include the main JSON  
    if use_llm:  
        files_to_zip.extend([  
            f"{base_filename}0.json",  # Intermediate JSON  
            f"{base_filename}00.wav"   # Output WAV  
        ])  
    else:  
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
   
    @after_this_request  
    def remove_file(response):  
        try:  
            # Remove ZIP file  
            if os.path.exists(zip_path):  
                os.remove(zip_path)  
                logger.info(f"Removed ZIP file: {zip_path}")  
            # Cleanup other files  
            cleanup_files(base_filename, use_llm, None)  
        except Exception as e:  
            logger.error(f"Error removing files: {e}")  
        return response   
   
    # Get Flask version and choose the appropriate send_file parameters  
    flask_version = get_flask_version()  
    logger.info(f"Detected Flask version: {flask_version}")  
    if flask_version >= (2, 0):  
        logger.info("Using Flask 2.0+ download format")  
        return send_file(zip_path, as_attachment=True, download_name=zip_filename)  
    else:  
        logger.info("Using pre-Flask 2.0 download format")  
        return send_file(zip_path, as_attachment=True, attachment_filename=zip_filename)  
   

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Clean up files for a given base filename"""
    try:
        data = request.get_json()
        base_filename = data.get('base_filename')
        use_llm = data.get('use_llm', False)
        use_ref_audio = data.get('use_reference_audio', False)
        
        logger.info(f"Received cleanup request for base_filename: {base_filename}, use_llm: {use_llm}, use_ref_audio: {use_ref_audio}")
        
        if not base_filename:
            return jsonify({"status": "error", "message": "No base filename provided"}), 400
            
        # Determine reference audio filename pattern
        ref_audio_filename = None
        if use_ref_audio:
            # Look for any reference audio files with this base pattern
            for file in os.listdir(app.config['UPLOAD_FOLDER']):
                if file.startswith(f"{base_filename}_ref"):
                    ref_audio_filename = file
                    break
        
        cleanup_files(base_filename, use_llm, ref_audio_filename)
        
        return jsonify({"status": "success", "message": "Files cleaned up successfully"})
        
    except Exception as e:
        error_msg = f"Error during cleanup: {str(e)}"
        logger.error(error_msg)
        return jsonify({"status": "error", "message": error_msg}), 500
   
   
if __name__ == '__main__':  
    app.run(debug=False, port=3000, host="0.0.0.0")
