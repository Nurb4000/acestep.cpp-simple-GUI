import os          
import json          
import subprocess          
import uuid          
from datetime import datetime          
from flask import Flask, request, jsonify, send_file, render_template          
from werkzeug.utils import secure_filename          
from pathlib import Path          
import zipfile          
import logging          
from io import BytesIO   	   
         
# --- Configuration & Constants ---          
BASE_DIR = Path(__file__).resolve().parent          
BIN_DIR = BASE_DIR / "bin"          
MODELS_DIR = BASE_DIR / "models"          
GENERATION_DIR = BASE_DIR / "generation"          
GENERATION_DIR.mkdir(exist_ok=True)   	   
         
# --- Logging Setup ---          
logging.basicConfig(          
    level=logging.INFO,          
    format='%(asctime)s [%(levelname)s] %(message)s',          
    handlers=[logging.StreamHandler()]          
)          
logger = logging.getLogger(__name__)   	   
         
# Default Configuration — numeric defaults are actual numbers (not strings)          
DEFAULTS = {          
    "caption": "", "lyrics": "", "bpm": 0, "duration": 0, "keyscale": "",          
    "timesignature": "", "vocal_language": "en", "seed": -1, "lm_batch_size": 1,          
    "synth_batch_size": 1, "lm_temperature": 0.85, "lm_cfg_scale": 2.0,          
    "lm_top_p": 0.9, "lm_top_k": 0, "lm_negative_prompt": "", "use_cot_caption": True,          
    "audio_codes": "", "inference_steps": 20, "guidance_scale": 0.0, "shift": 0.0,          
    "dcw_scaler": 0.0, "dcw_high_scaler": 0.0, "dcw_mode": "low",          
    "audio_cover_strength": 1.0, "cover_noise_strength": 0.0, "repainting_start": 0,          
    "repainting_end": -1, "latent_shift": 0.0, "latent_rescale": 1.0,          
    "custom_timesteps": "", "task_type": "text2music", "track": "", "solver": "euler",          
    "lm_mode": "generate", "output_format": "wav32", "peak_clip": 10, "mp3_bitrate": 128,          
    "synth_model": "./models/acestep-v15-xl-turbo-Q8_0.gguf",          
    "lm_model": "./models/acestep-5Hz-lm-4B-Q8_0.gguf",          
    "adapter": "", "adapter_scale": 1.0          
}   	   
         
MODEL_STEPS = {          
    "./models/acestep-v15-xl-turbo-Q8_0.gguf": 20,          
    "./models/acestep-v15-xl-base-Q8_0.gguf": 50,          
    "./models/acestep-v15-turbo-Q8_0.gguf": 10,          
    "./models/acestep-v15-sft-Q8_0.gguf": 30,          
    "./models/acestep-v15-xl-sft-Q8_0.gguf": 30,          
    "./models/acestep-v15-base-Q8_0.gguf": 50          
}   	   
         
# Field type categories          
INT_FIELDS = {          
    "bpm", "duration", "seed", "lm_batch_size", "synth_batch_size",          
    "inference_steps", "repainting_start", "repainting_end",          
    "peak_clip", "mp3_bitrate"          
}          
FLOAT_FIELDS = {          
    "lm_temperature", "lm_cfg_scale", "lm_top_p", "lm_top_k",          
    "guidance_scale", "shift", "dcw_scaler", "dcw_high_scaler",          
    "audio_cover_strength", "cover_noise_strength", "latent_shift",          
    "latent_rescale", "adapter_scale"          
}   	   
         
def safe_int(val, default=0):          
    try:          
        return int(float(val))          
    except (ValueError, TypeError):          
        return default   	   
         
def safe_float(val, default=0.0):          
    try:          
        return float(val)          
    except (ValueError, TypeError):          
        return default   	   
         
class MusicGenApp:          
    def __init__(self):          
        self.app = Flask(__name__, template_folder='templates')          
        self.app.config['SECRET_KEY'] = 'musicgen_secret_key_12345'          
        self.app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024          
        self._setup_routes()   	   
         
    def _setup_routes(self):          
        @self.app.route('/')          
        def index():          
            return render_template('index.html', defaults=DEFAULTS)   	   
         
        @self.app.route('/generate_json', methods=['POST'])          
        def generate_json_only():          
            form_data = request.form.to_dict()          
            src_audio_path = ref_audio_path = None          
            if 'src_audio' in request.files and request.files['src_audio'].filename:          
                file = request.files['src_audio']          
                filename = secure_filename(file.filename)          
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
                base_filename = f"musicgen_{timestamp}"          
                src_audio_path = GENERATION_DIR / f"src_{base_filename}_{uuid.uuid4().hex}_{filename}"          
                file.save(src_audio_path)          
            if 'ref_audio' in request.files and request.files['ref_audio'].filename:          
                file = request.files['ref_audio']          
                filename = secure_filename(file.filename)          
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
                base_filename = f"musicgen_{timestamp}"          
                ref_audio_path = GENERATION_DIR / f"ref_{base_filename}_{uuid.uuid4().hex}_{filename}"          
                file.save(ref_audio_path)          
            json_payload = {**DEFAULTS}          
            for key, val in form_data.items():          
                if key == "keyscale":          
                    json_payload[key] = str(val)          
                elif key in INT_FIELDS:          
                    json_payload[key] = safe_int(val, DEFAULTS.get(key, 0))          
                elif key in FLOAT_FIELDS:          
                    json_payload[key] = safe_float(val, DEFAULTS.get(key, 0.0))          
                else:          
                    json_payload[key] = val          
            # Strip model paths          
            for mkey in ("synth_model", "lm_model"):          
                if json_payload.get(mkey):          
                    json_payload[mkey] = os.path.basename(json_payload[mkey])          
            # Override inference steps          
            selected_model = form_data.get("synth_model")          
            if selected_model in MODEL_STEPS:          
                json_payload["inference_steps"] = MODEL_STEPS[selected_model]          
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
            base_filename = f"musicgen_{timestamp}"          
            # Generate JSON string for download          
            json_str = json.dumps(json_payload, indent=4)          
            # Return JSON response with filename for frontend to handle download          
            return jsonify({          
                "status": "success",          
                "message": "JSON file ready for download",          
                "json_filename": f"{base_filename}.json",          
                "json_content": json_str  # Pass content for frontend to download          
            })   	   
         
        @self.app.route('/generate', methods=['POST'])          
        def generate():          
            form_data = request.form.to_dict()          
            use_llm = form_data.pop('enhance_via_llm', 'false').lower() == 'true'          
            src_audio_path = ref_audio_path = None          
            if 'src_audio' in request.files and request.files['src_audio'].filename:          
                file = request.files['src_audio']          
                filename = secure_filename(file.filename)          
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
                base_filename = f"musicgen_{timestamp}"          
                src_audio_path = GENERATION_DIR / f"src_{base_filename}_{uuid.uuid4().hex}_{filename}"          
                file.save(src_audio_path)          
            if 'ref_audio' in request.files and request.files['ref_audio'].filename:          
                file = request.files['ref_audio']          
                filename = secure_filename(file.filename)          
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
                base_filename = f"musicgen_{timestamp}"          
                ref_audio_path = GENERATION_DIR / f"ref_{base_filename}_{uuid.uuid4().hex}_{filename}"          
                file.save(ref_audio_path)          
            json_payload = {**DEFAULTS}          
            for key, val in form_data.items():          
                if key == "keyscale":          
                    json_payload[key] = str(val)          
                elif key in INT_FIELDS:          
                    json_payload[key] = safe_int(val, DEFAULTS.get(key, 0))          
                elif key in FLOAT_FIELDS:          
                    json_payload[key] = safe_float(val, DEFAULTS.get(key, 0.0))          
                else:          
                    json_payload[key] = val          
            # Strip model paths          
            for mkey in ("synth_model", "lm_model"):          
                if json_payload.get(mkey):          
                    json_payload[mkey] = os.path.basename(json_payload[mkey])          
            # Override inference steps          
            selected_model = form_data.get("synth_model")          
            if selected_model in MODEL_STEPS:          
                json_payload["inference_steps"] = MODEL_STEPS[selected_model]          
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")          
            base_filename = f"musicgen_{timestamp}"          
            base_json_path = GENERATION_DIR / f"{base_filename}.json"          
            with open(base_json_path, 'w') as f:          
                json.dump(json_payload, f, indent=4)          
            # LLM enhancement (if requested)          
            if use_llm:          
                cmd = [str(BIN_DIR / "ace-lm"), "--models", str(MODELS_DIR), "--request", str(base_json_path)]          
                try:          
                    logger.info(f"Running LLM enhancement: {' '.join(cmd)}")          
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)          
                    llm_json_path = GENERATION_DIR / f"{base_filename}0.json"          
                    if not llm_json_path.exists():          
                        return jsonify({          
                            "status": "error",          
                            "message": "LLM output file missing.",          
                            "details": result.stdout + "\n" + result.stderr          
                        })          
                    with open(llm_json_path) as f:          
                        enhanced = json.load(f)          
                    logger.info("LLM enhancement successful.")          
                    return jsonify({          
                        "status": "enhanced",          
                        "base_filename": base_filename,          
                        "enhanced_data": enhanced          
                    })          
                except subprocess.CalledProcessError as e:          
                    return jsonify({          
                        "status": "error",          
                        "message": "LLM Generation Failed",          
                        "details": f"Exit code: {e.returncode}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"          
                    })          
            # Synthesis          
            extra_args = []          
            if src_audio_path:          
                extra_args += ["--src-audio", str(src_audio_path)]          
            if ref_audio_path:          
                extra_args += ["--ref-audio", str(ref_audio_path)]          
            if form_data.get('clamp_fp16') == 'on':          
                extra_args.append("--clamp-fp16")          
            cmd = [str(BIN_DIR / "ace-synth"), "--models", str(MODELS_DIR), "--request", str(base_json_path)] + extra_args          
            try:          
                logger.info(f"Running synthesis: {' '.join(cmd)}")          
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)          
                wav_files = list(GENERATION_DIR.glob(f"{base_filename}*.wav"))          
                if not wav_files:          
                    wav_files = sorted(GENERATION_DIR.glob("*.wav"), key=os.path.getmtime)          
                if wav_files:          
                    latest_wav = wav_files[-1]          
                    return jsonify({          
                        "status": "success",          
                        "base_filename": base_filename,          
                        "wav_url": f"/download/file?path={latest_wav.name}",          
                        "download_url": f"/download/all?base={base_filename}"          
                    })          
                else:          
                    return jsonify({          
                        "status": "error",          
                        "message": "No WAV file generated.",          
                        "details": f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"          
                    })          
            except subprocess.CalledProcessError as e:          
                return jsonify({          
                    "status": "error",          
                    "message": "Synthesis Failed",          
                    "details": f"Exit code: {e.returncode}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"          
                })   	   
         
        @self.app.route('/download/all')          
        def download_all():          
            base_name = request.args.get('base')          
            zip_path = GENERATION_DIR / f"{base_name}_bundle.zip"          
            with zipfile.ZipFile(zip_path, 'w') as zf:          
                for pattern in (f"{base_name}.json", f"{base_name}0.json"):          
                    f = GENERATION_DIR / pattern          
                    if f.exists():          
                        zf.write(f, f.name)          
                for f in GENERATION_DIR.glob(f"{base_name}*.wav"):          
                    zf.write(f, f.name)          
                # FIXED: Only include files from current generation using base_name prefix          
                for f in GENERATION_DIR.glob(f"src_{base_name}_*"):          
                    zf.write(f, f.name)          
                for f in GENERATION_DIR.glob(f"ref_{base_name}_*"):          
                    zf.write(f, f.name)          
            return send_file(zip_path, as_attachment=True)   	   
         
        @self.app.route('/download/file')          
        def download_file():          
            path_arg = request.args.get('path')          
            file_path = GENERATION_DIR / path_arg          
            if file_path.exists():          
                return send_file(file_path, as_attachment=True)          
            return jsonify({"error": "File not found"}), 404   	   
         
        @self.app.route('/cleanup', methods=['POST'])          
        def cleanup():          
            data = request.json or {}          
            base_name = data.get('base_filename')          
            if base_name:          
                for f in GENERATION_DIR.glob(f"{base_name}*"):          
                    try:          
                        f.unlink()          
                        logger.info(f"Deleted: {f.name}")          
                    except Exception as e:          
                        logger.warning(f"Failed to delete {f}: {e}")          
            return jsonify({"status": "cleaned"})   	   
         
        @self.app.route('/cleanup_all', methods=['POST'])          
        def cleanup_all():          
            try:          
                deleted = []          
                for f in GENERATION_DIR.iterdir():          
                    if f.is_file():          
                        f.unlink()          
                        deleted.append(f.name)          
                logger.info(f"Cleaned all: {deleted}")          
                return jsonify({"status": "cleaned_all", "deleted": deleted})          
            except Exception as e:          
                logger.error(f"Cleanup all failed: {e}")          
                return jsonify({"status": "error", "message": str(e)}), 500   	   
         
    def run(self, host='0.0.0.0', port=3000, debug=False):          
        self.app.run(host=host, port=port, debug=debug)   	   
         
if __name__ == '__main__':          
    app_instance = MusicGenApp()          
    print("Starting Music Gen Server...")          
    print(f"Generation Directory: {GENERATION_DIR.resolve()}")   	   
          
    app_instance.run(debug=True)
