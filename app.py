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

TRACK_NAMES = [
    "vocals", "backing_vocals", "drums", "bass", "guitar", "keyboard",
    "percussion", "strings", "synth", "fx", "brass", "woodwinds"
]
TURBO_KEYWORDS = ["turbo"]

EXTERNAL_LLM_URL = "http://10.0.1.27:8080/"
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
    "synth_batch_size": 1, "lm_temperature": 0.5, "lm_cfg_scale": 7,            
    "lm_top_p": 0.5, "lm_top_k": 0, "lm_negative_prompt": "bad audio, robotic vocals, autotune, distortion, spoken word, overly loud backing vocals, midi artifact, mechanical piano, glitchy drums, overcompressed, muddy mix, muddy bass, heavy reverb, crowd noise, background noise, unwanted silence, chaotic arrangement, predictable loops, repetitive", "use_cot_caption": True,            
    "audio_codes": "",     "inference_steps": 10, "guidance_scale": 0.0, "shift": 10,            
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
    "./models/acestep-v15-xl-turbo-Q8_0.gguf": 10,            
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


def save_uploaded_audio(file_key, base_filename):
    """Save uploaded audio file and return the path. Returns (Path, str) or (None, '')."""
    if file_key not in request.files or not request.files[file_key].filename:
        return None, ''
    file = request.files[file_key]
    filename = secure_filename(file.filename)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = "src" if file_key == "src_audio" else "ref"
    file_path = GENERATION_DIR / f"{prefix}_{base_filename}_{uuid.uuid4().hex}_{filename}"
    file.save(file_path)
    return file_path, filename


def build_json_payload(form_data):
    """Parse form data into json_payload with proper types and model overrides."""
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
    # Override inference steps based on selected model
    selected_model = form_data.get("synth_model")
    if selected_model in MODEL_STEPS:
        json_payload["inference_steps"] = MODEL_STEPS[selected_model]
    return json_payload


def build_synthesis_args(json_payload, src_audio_path, ref_audio_path, form_data):
    """Build extra command-line arguments for ace-synth."""
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
    # ADAPTER SUPPORT
    adapter_file = json_payload.get("adapter")
    if adapter_file and adapter_file.strip():
        extra_args += ["--adapters", str(ADAPTERS_DIR)]
        scale = json_payload.get("adapter_scale", 1.0)
        if scale != 1.0:
            extra_args += ["--adapter-scale", str(scale)]
    return extra_args


def extract_json_from_llm_response(content: str) -> dict:
    """
    Extract JSON from LLM response with multiple fallback strategies.
    
    Tries various patterns to handle different LLM response formats:
    - Direct JSON parsing
    - Markdown code fences (```json ... ```)
    - Plain code fences (``` ... ```)
    - JSON wrapped in other text
    - Trailing commas before closing braces/brackets
    """
    if not content or not content.strip():
        raise ValueError("Empty LLM response content")
    
    content = content.strip()
    logger.info(f"Attempting to extract JSON from LLM response ({len(content)} chars)")
    
    # Strategy 1: Direct JSON parse
    try:
        result = json.loads(content)
        logger.info("Successfully parsed JSON directly from LLM response")
        return result
    except json.JSONDecodeError as e:
        logger.info(f"Direct JSON parse failed: {e}")
    
    # Strategy 2: Try to find JSON in markdown code fences
    patterns = [
        (r'```json\s*\n([\s\S]*?)\n```', "markdown code fence with json tag"),
        (r'```\s*\n([\s\S]*?)\n```', "plain code fence"),
        (r'```json([\s\S]*?)```', "inline json code fence"),
        (r'```([\s\S]*?)```', "inline code fence"),
        (r'\{[\s\S]*\}', "curly brace block"),
        (r'\[[\s\S]*\]', "square bracket block"),
    ]
    
    for pattern, description in patterns:
        matches = re.findall(pattern, content, re.DOTALL)
        for match in matches:
            candidate = match.strip()
            if not candidate:
                continue
            try:
                logger.info(f"Successfully extracted JSON using {description} pattern")
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try to fix common JSON issues
                # Remove trailing commas before } or ]
                fixed = re.sub(r',\s*([}\]])', r'\1', candidate)
                try:
                    logger.info(f"Successfully extracted JSON using {description} pattern (after fixing trailing commas)")
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    continue
    
    # Strategy 3: Try to extract JSON by finding the first { or [ and last } or ]
    first_brace = content.find('{')
    first_bracket = content.find('[')
    
    if first_brace != -1:
        last_brace = content.rfind('}')
        if last_brace > first_brace:
            candidate = content[first_brace:last_brace + 1]
            try:
                logger.info("Successfully extracted JSON using curly brace extraction")
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try fixing trailing commas
                fixed = re.sub(r',\s*}', '}', candidate)
                try:
                    logger.info("Successfully extracted JSON using curly brace extraction (after fixing trailing commas)")
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass
    
    if first_bracket != -1:
        last_bracket = content.rfind(']')
        if last_bracket > first_bracket:
            candidate = content[first_bracket:last_bracket + 1]
            try:
                logger.info("Successfully extracted JSON using square bracket extraction")
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try fixing trailing commas
                fixed = re.sub(r',\s*]', ']', candidate)
                try:
                    logger.info("Successfully extracted JSON using square bracket extraction (after fixing trailing commas)")
                    return json.loads(fixed)
                except json.JSONDecodeError:
                    pass
    
    raise ValueError("Could not parse JSON from LLM response")


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
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"musicgen_{timestamp}"
            
            # Save uploaded audio files
            src_audio_path, _ = save_uploaded_audio("src_audio", base_filename)
            ref_audio_path, _ = save_uploaded_audio("ref_audio", base_filename)
            
            # Build json payload from form data
            json_payload = build_json_payload(form_data)
            
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

        def _is_turbo_model(model_path):
            model_basename = os.path.basename(model_path).lower()
            return any(kw in model_basename for kw in TURBO_KEYWORDS)

        def _rename_extract_output(base_filename, track_name, src_upload_name, suffix=""):
            """Rename the generated WAV to {src_stem}-{track}{suffix}.wav for extract tasks"""
            wav_files = list(GENERATION_DIR.glob(f"{base_filename}*.wav"))
            if not wav_files:
                wav_files = sorted(GENERATION_DIR.glob("*.wav"), key=os.path.getmtime)
            if wav_files:
                src_stem = Path(secure_filename(src_upload_name)).stem
                new_name = f"{src_stem}-{track_name}{suffix}.wav"
                new_path = GENERATION_DIR / new_name
                wav_files[-1].replace(new_path)
                return new_path
            return None

        @self.app.route('/generate', methods=['POST'])            
        def generate():            
            # Cleanup previous generation files first
            self._cleanup_generation_files()
            
            form_data = request.form.to_dict()            
            use_llm = form_data.pop('enhance_via_llm', 'false').lower() == 'true'
            src_upload_name = form_data.get('_src_original_name', '')
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"musicgen_{timestamp}"
            
            # Save uploaded audio files
            src_audio_path, src_upload_name = save_uploaded_audio("src_audio", base_filename)
            if not src_upload_name:
                src_upload_name = form_data.get('_src_original_name', '')
            ref_audio_path, _ = save_uploaded_audio("ref_audio", base_filename)
            
            # Build json payload from form data
            json_payload = build_json_payload(form_data)
            
            # Validate extract task
            is_extract = json_payload.get("task_type") == "extract"
            if is_extract:
                track_val = json_payload.get("track", "").strip()
                if not track_val:
                    return jsonify({
                        "status": "error",
                        "message": "Track selection is required for extract task."
                    }), 400
                if not src_audio_path:
                    return jsonify({
                        "status": "error",
                        "message": "Source audio is required for extract task."
                    }), 400
                if _is_turbo_model(json_payload.get("synth_model", "")):
                    return jsonify({
                        "status": "error",
                        "message": "Turbo models are not supported for extract task. Please select a Base or SFT model."
                    }), 400
            
            base_json_path = GENERATION_DIR / f"{base_filename}.json"            
            with open(base_json_path, 'w') as f:            
                json.dump(json_payload, f, indent=4)
            # LLM enhancement (if requested) — skipped for extract
            if use_llm and not is_extract:            
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
            extra_args = build_synthesis_args(json_payload, src_audio_path, ref_audio_path, form_data)
            cmd = [str(BIN_DIR / "ace-synth"), "--models", str(MODELS_DIR), "--request", str(base_json_path)] + extra_args            
            try:            
                logger.info(f"Running synthesis: {' '.join(cmd)}")            
                result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                # Handle extract output renaming
                if is_extract and src_upload_name:
                    renamed = _rename_extract_output(base_filename, json_payload.get("track", ""), src_upload_name)
                    if renamed:
                        latest_wav = renamed
                        return jsonify({
                            "status": "success",
                            "base_filename": base_filename,
                            "wav_url": f"/download/file?path={latest_wav.name}",
                            "download_url": f"/download/all?base={base_filename}"
                        })
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
                "EVERY LINE outside of brackets WILL BE SUNG AS LYRICS. There is no narration, "
                "description, or stage direction between tags — only words that will be vocalized.\n\n"
                "Never use parentheses () for musical or production descriptions, as the audio engine "
                "will accidentally speak or sing them as literal lyrics. All structure tags, instrumental "
                "breaks, and musical cues MUST be delimited strictly with brackets []. If a section has no "
                "vocals, use a single bracketed tag with no lines following it "
                "(e.g. [Intro Instrumental], [Guitar Solo], [Musical Interlude], [Outro Instrumental], "
                "[Intro - Industrial Atmosphere]).\n"
                "If a section has vocals, use the [Tag - modifier] pattern to keep style cues inside "
                "the brackets (e.g. [Outro -spoken words, fading out], [Chorus -anthemic], "
                "[Verse 1 -building intensity]). The lines after the tag must be actual singable "
                "lyrics — not production descriptions.\n\n"
                "WRONG: [Outro]\n"
                "       spoken words, fading out  ← this gets sung as lyrics!\n"
                "RIGHT: [Outro -spoken words, fading out]\n"
                "       Actual lyric lines here\n"
                "WRONG: [Intro - Industrial Atmosphere]\n"
                "       Synth drones, mechanical pulses  ← these get sung!\n"
                "RIGHT: [Intro - Industrial Atmosphere]\n"
                "       (no lines after — purely instrumental section)\n"
                "WRONG: [Verse 1] Guitars growl, drums enter with driving force\n"
                "WRONG: [Verse 1 -thundering drums, distorted guitars]\n"
                "       Rumbling bassline sets the foundation  ← this gets sung!\n"
                "       Guitar riffs cut through like lightning  ← this gets sung!\n"
                "RIGHT: [Verse 1 -thundering drums, distorted guitars]\n"
                "       We are the storm that breaks the night\n"
                "       Rising up with all our might\n\n"
                "## Your Task\n"
                "Analyze and enhance the user's song parameters. Return ONLY valid JSON — no explanations, "
                "no markdown, no code fences.\n\n"
                "## Lyrics Requirements (CRITICAL)\n"
                "- If the user's existing lyrics are '[instrumental]' or the song is instrumental, "
                "keep it instrumental — do NOT add vocal sections or sung lyrics.\n"
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
                "## Caption-Lyrics Consistency (IMPORTANT)\n"
                "Models are not good at resolving conflicts. Ensure consistency between caption and lyrics:\n"
                "- Instruments in Caption ↔ Instrumental section tags in Lyrics\n"
                "- Emotion in Caption ↔ Energy tags in Lyrics\n"
                "- Vocal description in Caption ↔ Vocal control tags in Lyrics\n\n"
                "CONFLICT RESOLUTION:\n"
                "- If caption and lyrics contradict, the model gets confused and quality decreases.\n"
                "- Example of CONFLICT: Caption says 'violin solo, classical' but lyrics have '[Guitar Solo]'\n"
                "- Example of CONSISTENT: Caption says 'violin solo, classical' and lyrics have '[Violin Solo]'\n"
                "- For mixed styles: use temporal evolution (e.g., 'Start with soft strings, middle becomes metal')\n"
                "- Avoid stacking too many tags in brackets — keep concise, one modifier per tag preferred.\n\n"
                "## Vocal and Energy Tags Reference\n"
                "Vocal style tags: [raspy vocal], [whispered], [falsetto], [powerful belting], "
                "[spoken word], [harmonies], [call and response], [ad-lib]\n"
                "Energy tags: [high energy], [low energy], [building energy], [explosive], "
                "[melancholic], [euphoric], [dreamy], [aggressive]\n\n"
                "## Avoiding AI-Flavored Lyrics\n"
                "Do NOT use:\n"
                "- Adjective stacking ('neon skies, electric hearts, endless dreams') — use concrete imagery\n"
                "- Inconsistent rhyme patterns — maintain natural flow\n"
                "- Blurred section boundaries — lyrics should not 'flow' across structure tags\n"
                "- Lines too long to sing — keep 6-10 syllables\n"
                "- Mixed metaphors — stick to one core metaphor per song\n\n"
                "## Output JSON fields (include only as relevant)\n"
                "caption should start with 2-3 song title suggestions wrapped in curly braces like "
                "{Title Idea One} {Another Title Idea} {Third Idea}, then a dense, descriptive paragraph "
                "detailing the genre, instruments, production style, sub-genres, vocals, and mood. "
                "Do NOT include BPM, key, or tempo in caption — use dedicated parameters instead. "
                "lyrics should contain the full structured lyrics with bracketed tags. "
                "Other fields (include all as separate JSON keys, do not omit): bpm, duration, keyscale, "
                "timesignature, vocal_language, lm_temperature, lm_cfg_scale, lm_top_p, lm_top_k, seed, "
                "shift. audio_codes should be left empty (it is for reference audio file codes, not style text)."
            )

            user_prompt = (
                "Current song parameters:\n"
                f"{json.dumps(current_params, indent=2)}\n\n"
                "Enhance these parameters following the songwriting guide strictly. "
                "Ensure lyrics have proper section tags ([Verse], [Chorus], etc.) and that "
                "the amount of lyrical content fits the specified duration. "
                "Check that caption and lyrics are consistent (instruments, emotion, vocal style match). "
                "Avoid AI-flavored lyrics (adjective stacking, mixed metaphors, inconsistent rhymes). "
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
                logger.info(f"Raw LLM response content length: {len(content)} chars")
                logger.info(f"Raw LLM response content: {content[:2000]}...")

                enhanced = extract_json_from_llm_response(content)

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
            
            # Generate a unique base name for this batch run
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            batch_base_filename = f"musicgen_batch_{timestamp}"
            
            # Save uploaded audio files
            src_audio_path, src_upload_name = save_uploaded_audio("src_audio", batch_base_filename)
            if not src_upload_name:
                src_upload_name = form_data.get('_src_original_name', '')
            ref_audio_path, _ = save_uploaded_audio("ref_audio", batch_base_filename)
            
            # Build json payload from form data
            json_payload = build_json_payload(form_data)
            
            # Validate extract task
            is_extract = json_payload.get("task_type") == "extract"
            if is_extract:
                track_val = json_payload.get("track", "").strip()
                if not track_val:
                    return jsonify({
                        "status": "error",
                        "message": "Track selection is required for extract task."
                    }), 400
                if not src_audio_path:
                    return jsonify({
                        "status": "error",
                        "message": "Source audio is required for extract task."
                    }), 400
                if _is_turbo_model(json_payload.get("synth_model", "")):
                    return jsonify({
                        "status": "error",
                        "message": "Turbo models are not supported for extract task. Please select a Base or SFT model."
                    }), 400
            
            # Generate batch JSON file
            batch_json_path = GENERATION_DIR / f"{batch_base_filename}.json"            
            with open(batch_json_path, 'w') as f:            
                json.dump(json_payload, f, indent=4)            
            # LLM enhancement for batch (if requested) — skipped for extract
            if use_llm and not is_extract:            
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
                extra_args = build_synthesis_args(json_payload, src_audio_path, ref_audio_path, form_data)
                cmd = [str(BIN_DIR / "ace-synth"), "--models", str(MODELS_DIR), "--request", str(batch_item_json_path)] + extra_args            
                try:            
                    logger.info(f"Running synthesis for batch item {i+1}: {' '.join(cmd)}")            
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    # Handle extract output renaming for batch items
                    if is_extract and src_upload_name:
                        renamed = _rename_extract_output(batch_item_filename, json_payload.get("track", ""), src_upload_name, f"_{i+1}")
                        if renamed:
                            batch_results.append({
                                "status": "success",
                                "base_filename": batch_item_filename,
                                "wav_url": f"/download/file?path={renamed.name}",
                                "download_url": f"/download/all?base={batch_item_filename}"
                            })
                            continue
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
                # For extract tasks, also include renamed wav files
                if is_extract:
                    for f in GENERATION_DIR.glob("*.wav"):
                        if not f.name.startswith("src_") and not f.name.startswith("ref_") and not f.name.startswith("musicgen_"):
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
                wavs = list(GENERATION_DIR.glob(f"{base_name}*.wav"))
                if not wavs:
                    # For extract tasks, the wav is renamed — include all non-prefixed wavs
                    for f in GENERATION_DIR.glob("*.wav"):
                        if not f.name.startswith("src_") and not f.name.startswith("ref_") and not f.name.startswith("musicgen_"):
                            zf.write(f, f.name)
                else:
                    for f in wavs:
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
                if f.is_file() and (
                    f.name.startswith("musicgen_")
                    or f.name.startswith("ref_")
                    or f.name.startswith("src_")
                    or (f.suffix == ".wav" and not f.name.startswith(("musicgen_", "src_", "ref_")))
                ):
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
