# app.py - Complete file with fixed batch functionality and adapter support
import os            
import json            
import subprocess            
import uuid            
import re
from datetime import datetime            
from flask import Flask, request, jsonify, send_file, render_template            
from werkzeug.utils import secure_filename            
from pathlib import Path            
import zipfile            
import logging            
from io import BytesIO
import requests

# --- Configuration & Constants            
BASE_DIR = Path(__file__).resolve().parent            
BIN_DIR = BASE_DIR / "bin"            
MODELS_DIR = BASE_DIR / "models"            
GENERATION_DIR = BASE_DIR / "generation"            
ADAPTERS_DIR = BASE_DIR / "adapters"

EXTERNAL_LLM_URL = "http://192.168.0.1:8080/" #example URL Replace with yours
ADAPTERS_DIR.mkdir(exist_ok=True)            
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
    "timesignature": "", "vocal_language": "en", "seed": 0, "lm_batch_size": 1,            
    "synth_batch_size": 1, "lm_temperature": 0.85, "lm_cfg_scale": 2.0,            
    "lm_top_p": 0.9, "lm_top_k": 0, "lm_negative_prompt": "bad audio, robotic vocals, autotune, distortion, spoken word, overly loud backing vocals, midi artifact, mechanical piano, glitchy drums, overcompressed, muddy mix, muddy bass, heavy reverb, crowd noise, background noise, unwanted silence, chaotic arrangement, predictable loops, repetitive", "use_cot_caption": True,            
    "audio_codes": "", "inference_steps": 20, "guidance_scale": 0.0, "shift": 0.0,            
    "dcw_scaler": 0.0, "dcw_high_scaler": 0.0, "dcw_mode": "low",            
    "audio_cover_strength": 1.0, "cover_noise_strength": 0.0, "repainting_start": 0,            
    "repainting_end": -1, "latent_shift": 0.0, "latent_rescale": 1.0,            
    "custom_timesteps": "", "task_type": "text2music", "track": "", "solver": "euler",            
    "lm_mode": "generate", "output_format": "wav32", "peak_clip": 10, "mp3_bitrate": 128,            
    "synth_model": "./models/acestep-v15-xl-turbo-Q8_0.gguf",            
    "lm_model": "./models/acestep-5Hz-lm-4B-Q8_0.gguf",            
    "adapter": "", "adapter_scale": 1.0  # <-- ADDED
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

def get_adapter_files():
    """Returns list of adapter files in ADAPTERS_DIR (all extensions)"""
    try:
        return [f.name for f in ADAPTERS_DIR.glob("*") if f.is_file()]
    except Exception as e:
        logger.warning(f"Could not list adapters: {e}")
        return []

class MusicGenApp:            
    def __init__(self):            
        self.app = Flask(__name__, template_folder='templates')            
        self.app.config['SECRET_KEY'] = 'musicgen_secret_key_12345'            
        self.app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024
        guide_path = BASE_DIR / "Song Writing Guide.md"
        if guide_path.exists():
            self.song_writing_guide = guide_path.read_text(encoding='utf-8')
            logger.info("Song Writing Guide loaded successfully.")
        else:
            self.song_writing_guide = ""
            logger.warning("Song Writing Guide.md not found - external LLM enhance will not include format guide.")
        self._setup_routes()    

    def _setup_routes(self):            
        @self.app.route('/')            
        def index():            
            adapter_files = get_adapter_files()
            return render_template('index.html', defaults=DEFAULTS, adapter_files=adapter_files)    

        @self.app.route('/generate_json', methods=['POST'])            
        def generate_json_only():            
            # Cleanup previous generation files first
            self._cleanup_generation_files()
            
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

        @self.app.route('/analyze_llm', methods=['POST'])
        def analyze_llm():
            # Cleanup previous generation files first
            self._cleanup_generation_files()
            
            form_data = request.form.to_dict()
            ref_audio_path = None

            # 1. Locate or Save Reference Audio
            if 'ref_audio' in request.files and request.files['ref_audio'].filename:
                file = request.files['ref_audio']
                filename = secure_filename(file.filename)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base_filename = f"musicgen_{timestamp}"
                ref_audio_path = GENERATION_DIR / f"ref_{base_filename}_{uuid.uuid4().hex}_{filename}"
                file.save(ref_audio_path)
            else:
                return jsonify({
                    "status": "error",
                    "message": "No reference audio provided."
                }), 400
            # 2. Construct Command
            analysis_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            analysis_base = f"analysis_{analysis_timestamp}"
            output_json_path = GENERATION_DIR / f"{analysis_base}.json"
            cmd = [
                str(BIN_DIR / "ace-understand"),
                "--src-audio", str(ref_audio_path),
                "--models", str(MODELS_DIR),
                "-o", str(output_json_path)
            ]
            try:
                logger.info(f"Running LLM Analyze: {' '.join(cmd)}")
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)

                if not output_json_path.exists():
                    return jsonify({
                        "status": "error",
                        "message": "Analysis output file was not created.",
                        "details": result.stdout + "\n" + result.stderr
                    })
                # 3. Read the JSON
                with open(output_json_path, 'r') as f:
                    analysis_data = json.load(f)
                # 4. Cleanup (Delete the temporary analysis file)
                try:
                    output_json_path.unlink()
                    logger.info(f"Deleted temporary analysis file: {output_json_path.name}")
                except Exception as e:
                    logger.warning(f"Could not delete temp file {output_json_path}: {e}")
                # 5. Return data to frontend
                return jsonify({
                    "status": "success",
                    "analysis_data": analysis_data
                })
            except subprocess.CalledProcessError as e:
                return jsonify({
                    "status": "error",
                    "message": "LLM Analyze Failed",
                    "details": f"Exit code: {e.returncode}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"
                }), 500

        @self.app.route('/generate', methods=['POST'])            
        def generate():            
            # Cleanup previous generation files first
            self._cleanup_generation_files()
            
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
            if form_data.get('no_fa') == 'on':
                extra_args.append("--no-fa")
            extra_args += ["--vae-chunk", "512", "--vae-overlap", "128"]
            # ADAPTER SUPPORT: Add --adapters directory only (not full file path)
            adapter_file = json_payload.get("adapter")
            if adapter_file and adapter_file.strip():
                extra_args += ["--adapters", str(ADAPTERS_DIR)]
                # Add scale only if non-default
                scale = json_payload.get("adapter_scale", 1.0)
                if scale != 1.0:
                    extra_args += ["--adapter-scale", str(scale)]
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

        @self.app.route('/enhance_external', methods=['POST'])
        def enhance_external():
            self._cleanup_generation_files()

            form_data = request.form.to_dict()

            relevant_keys = {
                "caption", "lyrics", "duration", "bpm", "keyscale",
                "timesignature", "vocal_language", "seed", "shift",
                "audio_codes", "lm_temperature", "lm_cfg_scale",
                "lm_top_p", "lm_top_k", "task_type"
            }
            current_params = {k: v for k, v in form_data.items() if k in relevant_keys}

            guide_content = self.song_writing_guide
            system_prompt = (
                "You are an expert AI music producer, lyricist, and prompt engineer for ACE-Step 1.5, "
                "specializing in song generation.\n\n"
                f"{guide_content}\n\n"
                "## CRITICAL INSTRUCTION FOR AUDIO SYNTHESIS\n"
                "Never use parentheses () for musical or production descriptions, as the audio engine "
                "will accidentally speak or sing them as literal lyrics. All structure tags, instrumental "
                "breaks, and musical cues MUST be delimited strictly with brackets []. If a section has no "
                "vocals, use specific tags like [Intro Instrumental], [Guitar Solo], [Musical Interlude], "
                "or [Outro Instrumental]. Do not include descriptive words outside of brackets.\n"
                "WRONG: [Intro] Heavy guitar swells rise, building tension\n"
                "RIGHT: [Intro Instrumental]\n"
                "WRONG: [Verse 1] Guitars growl, drums enter with driving force\n"
                "RIGHT: [Verse 1]\n"
                "       First line of actual lyrics here\n"
                "       Second line of lyrics\n\n"
                "## Your Task\n"
                "Analyze and enhance the user's song parameters. Return ONLY valid JSON — no explanations, "
                "no markdown, no code fences.\n\n"
                "## Lyrics Requirements (CRITICAL)\n"
                "- Lyrics MUST include proper song structure tags: [Intro], [Verse 1], [Verse 2], [Chorus], "
                "[Bridge], [Guitar Solo], [Keyboard Interlude], [Outro Instrumental], etc.\n"
                "- Use brackets [] for ALL structural and musical cues. Never use parentheses () for these.\n"
                "- Match lyric length and number of sections to the song's duration:\n"
                "  * <60s: 1 verse + 1 chorus (6-10 lines total)\n"
                "  * 60-120s: 1-2 verses + 2 choruses\n"
                "  * 120-180s: 2 verses + 2 choruses + optional bridge\n"
                "  * >180s: 2-3 verses + 2-3 choruses + bridge + intro/outro\n"
                "- Do NOT generate absurdly long lyrics for short durations or vice versa.\n"
                "- Each lyric line should be 6-10 syllables and metered rhythmically so the audio synthesis "
                "aligns properly.\n"
                "- Use blank lines between sections.\n\n"
                "## Output JSON fields (include only as relevant)\n"
                "caption should be a dense, descriptive paragraph detailing the genre, instruments, production "
                "style, sub-genres, vocals, and mood (reference BPM and key-scale in the caption text as well). "
                "lyrics should contain the full structured lyrics with bracketed tags. "
                "Other fields (include all as separate JSON keys, do not omit): bpm, duration, keyscale, "
                "timesignature, vocal_language, lm_temperature, lm_cfg_scale, lm_top_p, lm_top_k, seed, "
                "shift, audio_codes"
            )

            user_prompt = (
                "Current song parameters:\n"
                f"{json.dumps(current_params, indent=2)}\n\n"
                "Enhance these parameters following the songwriting guide strictly. "
                "Make sure lyrics have proper section tags ([Verse], [Chorus], etc.) and that "
                "the amount of lyrical content fits the specified duration. "
                "Return ONLY valid JSON."
            )

            try:
                logger.info("Calling external LLM for enhancement...")
                resp = requests.post(
                    f"{EXTERNAL_LLM_URL.rstrip('/')}/v1/chat/completions",
                    json={
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        "temperature": 0.7,
                        "max_tokens": 4096
                    },
                    timeout=300
                )
                resp.raise_for_status()
                result = resp.json()
                content = result["choices"][0]["message"]["content"]

                try:
                    enhanced = json.loads(content)
                except json.JSONDecodeError:
                    json_match = re.search(r'```(?:json)?\s*\n?([\s\S]*?)```', content)
                    if json_match:
                        enhanced = json.loads(json_match.group(1).strip())
                    else:
                        raise ValueError("Could not parse JSON from LLM response")

                logger.info("External LLM enhancement successful.")
                return jsonify({
                    "status": "enhanced",
                    "enhanced_data": enhanced
                })

            except requests.exceptions.RequestException as e:
                return jsonify({
                    "status": "error",
                    "message": f"External LLM request failed: {str(e)}"
                }), 500
            except Exception as e:
                return jsonify({
                    "status": "error",
                    "message": f"External LLM enhancement failed: {str(e)}"
                }), 500

        @self.app.route('/generate_batch', methods=['POST'])            
        def generate_batch():            
            # Cleanup previous generation files first
            self._cleanup_generation_files()
            
            form_data = request.form.to_dict()            
            use_llm = form_data.pop('enhance_via_llm', 'false').lower() == 'true'            
            batch_size = safe_int(form_data.get('batch_size', 1), 1)            
            src_audio_path = ref_audio_path = None            
            
            # Generate a unique base name for this batch run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_base_filename = f"musicgen_batch_{timestamp}"
            
            # Save reference and source audio with the batch base filename
            if 'src_audio' in request.files and request.files['src_audio'].filename:            
                file = request.files['src_audio']            
                filename = secure_filename(file.filename)            
                src_audio_path = GENERATION_DIR / f"src_{batch_base_filename}_{uuid.uuid4().hex}_{filename}"            
                file.save(src_audio_path)            
            
            if 'ref_audio' in request.files and request.files['ref_audio'].filename:            
                file = request.files['ref_audio']            
                filename = secure_filename(file.filename)            
                ref_audio_path = GENERATION_DIR / f"ref_{batch_base_filename}_{uuid.uuid4().hex}_{filename}"            
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
            # Generate batch JSON file
            batch_json_path = GENERATION_DIR / f"{batch_base_filename}.json"            
            with open(batch_json_path, 'w') as f:            
                json.dump(json_payload, f, indent=4)            
            # LLM enhancement for batch (if requested)            
            if use_llm:            
                cmd = [str(BIN_DIR / "ace-lm"), "--models", str(MODELS_DIR), "--request", str(batch_json_path)]            
                try:            
                    logger.info(f"Running LLM enhancement for batch: {' '.join(cmd)}")            
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)            
                    llm_json_path = GENERATION_DIR / f"{batch_base_filename}0.json"            
                    if not llm_json_path.exists():            
                        return jsonify({            
                            "status": "error",            
                            "message": "LLM output file missing for batch.",            
                            "details": result.stdout + "\n" + result.stderr            
                        })            
                    with open(llm_json_path) as f:            
                        enhanced = json.load(f)            
                    logger.info("LLM enhancement successful for batch.")            
                    # Apply enhanced values to batch settings
                    for key, val in enhanced.items():            
                        if key in json_payload:            
                            json_payload[key] = val            
                except subprocess.CalledProcessError as e:            
                    return jsonify({            
                        "status": "error",            
                        "message": "LLM Batch Enhancement Failed",            
                        "details": f"Exit code: {e.returncode}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"            
                    })            
            # Generate batch of music
            batch_results = []            
            batch_errors = []            
            for i in range(batch_size):            
                # Generate random seed for each item
                seed = safe_int(form_data.get('seed', 0), 0)            
                if seed == 0:            
                    seed = int(uuid.uuid4().hex[:8], 16) % (2**32 - 1) + 1            
                json_payload["seed"] = seed            
                batch_item_filename = f"{batch_base_filename}_{i+1}"            
                batch_item_json_path = GENERATION_DIR / f"{batch_item_filename}.json"            
                with open(batch_item_json_path, 'w') as f:            
                    json.dump(json_payload, f, indent=4)            
                # Synthesis            
                extra_args = []            
                if src_audio_path:            
                    extra_args += ["--src-audio", str(src_audio_path)]            
                if ref_audio_path:            
                    extra_args += ["--ref-audio", str(ref_audio_path)]            
                if form_data.get('clamp_fp16') == 'on':            
                    extra_args.append("--clamp-fp16")            
                if form_data.get('no_fa') == 'on':
                    extra_args.append("--no-fa")
                extra_args += ["--vae-chunk", "512", "--vae-overlap", "128"]
                # ADAPTER SUPPORT: Add --adapters directory only (not full file path)
                adapter_file = json_payload.get("adapter")
                if adapter_file and adapter_file.strip():
                    extra_args += ["--adapters", str(ADAPTERS_DIR)]
                    # Add scale only if non-default
                    scale = json_payload.get("adapter_scale", 1.0)
                    if scale != 1.0:
                        extra_args += ["--adapter-scale", str(scale)]
                cmd = [str(BIN_DIR / "ace-synth"), "--models", str(MODELS_DIR), "--request", str(batch_item_json_path)] + extra_args            
                try:            
                    logger.info(f"Running synthesis for batch item {i+1}: {' '.join(cmd)}")            
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)            
                    wav_files = list(GENERATION_DIR.glob(f"{batch_item_filename}*.wav"))            
                    if not wav_files:            
                        wav_files = sorted(GENERATION_DIR.glob("*.wav"), key=os.path.getmtime)            
                    if wav_files:            
                        latest_wav = wav_files[-1]            
                        batch_results.append({            
                            "status": "success",            
                            "base_filename": batch_item_filename,            
                            "wav_url": f"/download/file?path={latest_wav.name}",            
                            "download_url": f"/download/all?base={batch_item_filename}"            
                        })            
                    else:            
                        batch_errors.append({            
                            "status": "error",            
                            "message": f"No WAV file generated for batch item {i+1}.",            
                            "details": f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"            
                        })            
                except subprocess.CalledProcessError as e:            
                    batch_errors.append({            
                        "status": "error",            
                        "message": f"Synthesis Failed for batch item {i+1}",            
                        "details": f"Exit code: {e.returncode}\nSTDOUT:\n{e.stdout}\nSTDERR:\n{e.stderr}"            
                    })            
            # If there were errors, return them
            if batch_errors:            
                return jsonify({            
                    "status": "partial_success",            
                    "message": "Some batch items failed",            
                    "batch_results": batch_results,            
                    "batch_errors": batch_errors            
                })            
            # Create zip bundle for all batch results
            zip_path = GENERATION_DIR / f"{batch_base_filename}_bundle.zip"            
            with zipfile.ZipFile(zip_path, 'w') as zf:            
                # Add all JSON files
                for f in GENERATION_DIR.glob(f"{batch_base_filename}_*.json"):            
                    zf.write(f, f.name)            
                # Add all WAV files
                for f in GENERATION_DIR.glob(f"{batch_base_filename}_*.wav"):            
                    zf.write(f, f.name)            
                # Add reference audio files if they exist
                if ref_audio_path and ref_audio_path.exists():
                    zf.write(ref_audio_path, ref_audio_path.name)            
                # Add source audio files if they exist
                if src_audio_path and src_audio_path.exists():
                    zf.write(src_audio_path, src_audio_path.name)            
            # Return the zip file for download
            return jsonify({            
                "status": "success",            
                "message": "Batch generation completed",            
                "base_filename": batch_base_filename,            
                "download_url": f"/download/batch?base={batch_base_filename}"            
            })    

        @self.app.route('/download/batch')            
        def download_batch():            
            base_name = request.args.get('base')            
            zip_path = GENERATION_DIR / f"{base_name}_bundle.zip"            
            if zip_path.exists():            
                return send_file(zip_path, as_attachment=True)            
            return jsonify({"error": "Batch bundle not found"}), 404    

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

        # Removed the cleanup_all route entirely
        
    def _cleanup_generation_files(self):
        """Cleanup files from previous generation runs"""
        try:
            deleted = []
            for f in GENERATION_DIR.iterdir():
                if f.is_file() and (f.name.startswith("musicgen_") or f.name.startswith("ref_") or f.name.startswith("src_")):
                    f.unlink()
                    deleted.append(f.name)
            if deleted:
                logger.info(f"Cleaned previous generation files: {deleted}")
        except Exception as e:
            logger.error(f"Cleanup previous files failed: {e}")

    def run(self, host='0.0.0.0', port=3000, debug=False):            
        self.app.run(host=host, port=port, debug=debug)    

if __name__ == '__main__':            
    app_instance = MusicGenApp()            
    print("Starting Music Gen Server...")            
    print(f"Generation Directory: {GENERATION_DIR.resolve()}")            
    print(f"Adapter Directory: {ADAPTERS_DIR.resolve()}")

    app_instance.run(debug=True)
