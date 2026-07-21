import base64
import ast
import math
import operator
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import requests
from flask import Flask, Response, jsonify, render_template, request, stream_with_context

# ==========================================================
# MEDIAPIPE HANDS IMPORT (robust)
# ==========================================================
# Prefer the public mediapipe import path (works on typical installs).
# Fall back to the internal python.solutions path if needed.
try:
    import mediapipe as mp
    mp_hands = mp.solutions.hands
except Exception:
    from mediapipe.python.solutions import hands as mp_hands


try:
    from flask_cors import CORS
except ImportError:

    def CORS(*args, **kwargs):
        return None


try:
    from dotenv import load_dotenv
except ImportError:

    def load_dotenv(*args, **kwargs):
        dotenv_path = kwargs.get("dotenv_path") or ".env"
        override = kwargs.get("override", True)

        if not os.path.exists(dotenv_path):
            return False

        with open(dotenv_path, "r", encoding="utf-8") as f:
            for raw in f:
                line = raw.strip()

                if (
                    not line
                    or line.startswith("#")
                    or "=" not in line
                ):
                    continue

                key, value = line.split("=", 1)
                key = key.strip()

                value = (
                    value
                    .strip()
                    .strip('"')
                    .strip("'")
                )

                if override or key not in os.environ:
                    os.environ[key] = value

        return True


# ==========================================================
# LOAD ENV
# ==========================================================

env_path = Path(__file__).parent / ".env"

load_dotenv(
    dotenv_path=env_path,
    override=True
)


# ==========================================================
# CONFIG
# ==========================================================

DEFAULT_PROBLEM_PROMPT = (
    "Draw a math problem "
    "(e.g., solve for x: 2x+3=7)"
)

GEMINI_SERVER_HOST = os.getenv(
    "GEMINI_SERVER_HOST",
    "127.0.0.1"
)

GEMINI_SERVER_PORT = os.getenv(
    "GEMINI_SERVER_PORT",
    "6001"
)

GEMINI_SERVER_URL = os.getenv(
    "GEMINI_SERVER_URL",
    f"http://{GEMINI_SERVER_HOST}:"
    f"{GEMINI_SERVER_PORT}/solve"
)

GEMINI_SERVER_HEALTH_URL = os.getenv(
    "GEMINI_SERVER_HEALTH_URL",
    f"http://{GEMINI_SERVER_HOST}:"
    f"{GEMINI_SERVER_PORT}/health",
)

GEMINI_SERVER_PYTHON = os.getenv(
    "GEMINI_SERVER_PYTHON",
    ""
).strip()

ENABLE_CV = (
    os.getenv(
        "ENABLE_CV",
        "0"
    ).lower()
    in (
        "1",
        "true",
        "yes"
    )
)


# ==========================================================
# DRAWING CONFIG
# ==========================================================

CANVAS_SIZE = 500

LINE_COLOR = (
    255,
    255,
    255
)

LINE_THICKNESS = 8

DOT_COLOR = (
    0,
    0,
    255
)

SMOOTHING_FACTOR = 0.3

COOLDOWN_FRAMES = 30

CAMERA_WIDTH = 320

CAMERA_HEIGHT = 240

CAMERA_FPS = 24

STREAM_FPS = 20

CAMERA_STATE_INTERVAL = 0.20


# ==========================================================
# FLASK SETUP
# ==========================================================

cli = sys.modules.get("flask.cli")

if cli is not None:
    cli.show_server_banner = (
        lambda *x: None
    )


app = Flask(__name__)

CORS(app)


# ==========================================================
# LOCKS
# ==========================================================

state_lock = threading.Lock()

canvas_lock = threading.Lock()

gemini_process_lock = threading.Lock()

cv_running_lock = threading.Lock()

background_solve_lock = threading.Lock()


# ==========================================================
# GLOBALS
# ==========================================================

gemini_process = None

cv_thread = None

cv_stop_event = threading.Event()

latest_frame_bytes = None

frame_lock = threading.Lock()


drawing_canvas = np.zeros(
    (
        CANVAS_SIZE,
        CANVAS_SIZE,
        3
    ),
    dtype=np.uint8
)


# ==========================================================
# APPLICATION STATE
# ==========================================================

app_state = {

    "drawing_active": True,

    "analyzing": False,

    "cooldown": False,

    "operation_mode": "SOLVE",

    "input_mode":
        "CV"
        if ENABLE_CV
        else "MOUSE",

    "problem":
        DEFAULT_PROBLEM_PROMPT,

    "solution_type": "",

    "solution_text": "",

    "plottable_equation": "",

    "drawing_canvas_b64": "",

    "drawing_overlay_b64": "",

    "camera_frame_b64": "",

    "camera_running": False,

    "camera_state": "stopped",

    "camera_error": "",

}


# ==========================================================
# STATE HELPERS
# ==========================================================

def set_state(**kwargs):

    with state_lock:

        app_state.update(kwargs)


def get_state_copy():

    with state_lock:

        return dict(app_state)


def reset_solution_state():

    set_state(

        analyzing=False,

        cooldown=False,

        problem=DEFAULT_PROBLEM_PROMPT,

        solution_type="",

        solution_text="",

        plottable_equation="",

        drawing_canvas_b64="",

        drawing_overlay_b64="",

        camera_frame_b64="",

    )


# ==========================================================
# BASE64 HELPER
# ==========================================================

def normalize_base64_image(raw_value):

    if not raw_value:

        return ""

    value = raw_value.strip()

    if (
        value.startswith("data:image")
        and "," in value
    ):

        value = value.split(
            ",",
            1
        )[1]

    return value


# ==========================================================
# SAFE MATH OPERATORS
# ==========================================================

SAFE_BINARY_OPS = {

    ast.Add:
        operator.add,

    ast.Sub:
        operator.sub,

    ast.Mult:
        operator.mul,

    ast.Div:
        operator.truediv,

    ast.Pow:
        operator.pow,

    ast.Mod:
        operator.mod,

}


SAFE_UNARY_OPS = {

    ast.UAdd:
        operator.pos,

    ast.USub:
        operator.neg,

}


SAFE_FUNCTIONS = {

    "abs":
        abs,

    "sqrt":
        math.sqrt,

    "sin":
        math.sin,

    "cos":
        math.cos,

    "tan":
        math.tan,

    "log":
        math.log,

    "ln":
        math.log,

}


# ==========================================================
# NORMALIZE MATH EXPRESSION
# ==========================================================

def normalize_math_expression(
    expression
):

    text = (
        expression
        .lower()
        .strip()
    )

    text = text.replace(
        "^",
        "**"
    )

    text = re.sub(
        r"(?<=\d)(?=[a-z(])",
        "*",
        text
    )

    text = re.sub(
        r"(?<=x)(?=\d)",
        "*",
        text
    )

    text = re.sub(
        r"(?<=x)(?=\()",
        "*",
        text
    )

    text = re.sub(
        r"(?<=\))(?=[\dx(])",
        "*",
        text
    )

    return text


# ==========================================================
# SAFE EXPRESSION EVALUATOR
# ==========================================================

def safe_eval_expression(
    expression,
    x_value=None
):

    normalized = (
        normalize_math_expression(
            expression
        )
    )

    tree = ast.parse(
        normalized,
        mode="eval"
    )

    def eval_node(node):

        if isinstance(
            node,
            ast.Expression
        ):

            return eval_node(
                node.body
            )

        if (
            isinstance(
                node,
                ast.Constant
            )
            and isinstance(
                node.value,
                (
                    int,
                    float
                )
            )
        ):

            return node.value

        if isinstance(
            node,
            ast.Name
        ):

            if (
                node.id == "x"
                and x_value is not None
            ):

                return x_value

            if node.id == "pi":

                return math.pi

            if node.id == "e":

                return math.e

            raise ValueError(
                f"Unknown symbol: "
                f"{node.id}"
            )

        if (
            isinstance(
                node,
                ast.BinOp
            )
            and type(node.op)
            in SAFE_BINARY_OPS
        ):

            return (
                SAFE_BINARY_OPS[
                    type(node.op)
                ](
                    eval_node(
                        node.left
                    ),
                    eval_node(
                        node.right
                    )
                )
            )

        if (
            isinstance(
                node,
                ast.UnaryOp
            )
            and type(node.op)
            in SAFE_UNARY_OPS
        ):

            return (
                SAFE_UNARY_OPS[
                    type(node.op)
                ](
                    eval_node(
                        node.operand
                    )
                )
            )

        if (
            isinstance(
                node,
                ast.Call
            )
            and isinstance(
                node.func,
                ast.Name
            )
            and node.func.id
            in SAFE_FUNCTIONS
        ):

            args = [

                eval_node(arg)

                for arg
                in node.args

            ]

            return (
                SAFE_FUNCTIONS[
                    node.func.id
                ](
                    *args
                )
            )

        raise ValueError(

            "Only arithmetic and "
            "single-variable x equations "
            "are supported locally."

        )

    return eval_node(tree)


# ==========================================================
# FORMAT NUMBER
# ==========================================================

def format_number(value):

    if (
        abs(
            value
            - round(value)
        )
        < 1e-10
    ):

        return str(
            int(
                round(value)
            )
        )

    return f"{value:.10g}"


# ==========================================================
# LOCAL TEXT SOLVER
# ==========================================================

def solve_text_problem(
    problem_text
):

    problem = (
        problem_text
        or ""
    ).strip()

    if not problem:

        raise ValueError(

            "Enter an equation or "
            "arithmetic expression first."

        )

    if "=" not in problem:

        value = (
            safe_eval_expression(
                problem
            )
        )

        return {

            "problem":
                problem,

            "solution_type":
                "Arithmetic",

            "solution_text":
                (
                    f"Expression: "
                    f"{problem}\n"

                    f"Result: "
                    f"{format_number(value)}"
                ),

            "plottable_equation":
                "",

        }

    left, right = (
        problem.split(
            "=",
            1
        )
    )

    def f(x_value):

        return (

            safe_eval_expression(
                left,
                x_value=x_value
            )

            -

            safe_eval_expression(
                right,
                x_value=x_value
            )

        )

    f0 = f(0)

    f1 = f(1)

    slope = (
        f1
        - f0
    )

    if abs(slope) < 1e-12:

        if abs(f0) < 1e-12:

            answer = (
                "All real numbers "
                "satisfy this equation."
            )

        else:

            answer = (
                "No solution."
            )

        return {

            "problem":
                problem,

            "solution_type":
                "Equation",

            "solution_text":
                (
                    f"Equation: "
                    f"{problem}\n"

                    f"Result: "
                    f"{answer}"
                ),

            "plottable_equation":
                "",

        }

    x_solution = (
        -f0
        / slope
    )

    check_left = (
        safe_eval_expression(
            left,
            x_value=x_solution
        )
    )

    check_right = (
        safe_eval_expression(
            right,
            x_value=x_solution
        )
    )

    return {

        "problem":
            problem,

        "solution_type":
            "Equation",

        "solution_text":
            (
                f"Equation: "
                f"{problem}\n"

                f"Move all terms to one side: "
                f"f(x) = left - right\n"

                f"f(0) = "
                f"{format_number(f0)}\n"

                f"f(1) - f(0) = "
                f"{format_number(slope)}\n"

                f"Solve f(x) = 0: "
                f"x = "
                f"{format_number(x_solution)}\n"

                f"Check: left = "
                f"{format_number(check_left)}, "

                f"right = "
                f"{format_number(check_right)}"
            ),

        "plottable_equation":
            "",

    }


# ==========================================================
# GEMINI HELPERS
# ==========================================================

def local_gemini_url():

    parsed = urlparse(
        GEMINI_SERVER_URL
    )

    return (
        parsed.hostname
        in (
            "127.0.0.1",
            "localhost"
        )
    )


def get_gemini_python_executable():

    if GEMINI_SERVER_PYTHON:

        return GEMINI_SERVER_PYTHON

    known_conda_python = Path(

        r"C:\Users\featv\anaconda3"
        r"\envs\gemini_env"
        r"\python.exe"

    )

    if known_conda_python.exists():

        return str(
            known_conda_python
        )

    return sys.executable


def gemini_health_ok(
    timeout=1
):

    try:

        response = requests.get(

            GEMINI_SERVER_HEALTH_URL,

            timeout=timeout

        )

        return response.ok

    except requests.RequestException:

        return False


def start_gemini_server_if_needed():

    global gemini_process

    if gemini_health_ok():

        return (
            True,
            ""
        )

    if not local_gemini_url():

        return (

            False,

            (
                "Gemini server is not "
                "reachable at "
                f"{GEMINI_SERVER_URL}."
            )

        )

    with gemini_process_lock:

        if (
            gemini_process is not None
            and gemini_process.poll()
            is None
        ):

            pass

        else:

            python_exe = (
                get_gemini_python_executable()
            )

            server_path = (

                Path(__file__).parent

                / "gemini_server.py"

            )

            creationflags = 0

            if os.name == "nt":

                creationflags = (

                    subprocess.CREATE_NO_WINDOW

                    |

                    subprocess.CREATE_NEW_PROCESS_GROUP

                    |

                    subprocess.DETACHED_PROCESS

                )

            stdout_log = open(

                Path(__file__).parent
                / "gemini_server.out.log",

                "a",

                encoding="utf-8"

            )

            stderr_log = open(

                Path(__file__).parent
                / "gemini_server.err.log",

                "a",

                encoding="utf-8"

            )

            try:

                gemini_process = subprocess.Popen(

                    [
                        python_exe,
                        str(server_path)
                    ],

                    cwd=str(
                        Path(__file__).parent
                    ),

                    stdout=stdout_log,

                    stderr=stderr_log,

                    creationflags=creationflags,

                )

            except Exception as e:

                return (

                    False,

                    (
                        "Could not start "
                        "Gemini server with "
                        f"{python_exe}: {e}"
                    )

                )

    for _ in range(30):

        if gemini_health_ok(
            timeout=1
        ):

            return (
                True,
                ""
            )

        if (
            gemini_process is not None
            and gemini_process.poll()
            is not None
        ):

            return (

                False,

                (
                    "Gemini server started "
                    "but exited immediately. "
                    "Check gemini_server.err.log "
                    "for the API key or "
                    "dependency error."
                )

            )

        time.sleep(0.5)

    return (

        False,

        (
            "Gemini server did not become "
            "ready at "
            f"{GEMINI_SERVER_HEALTH_URL}."
        )

    )


# ==========================================================
# GEMINI REQUEST
# ==========================================================

def call_gemini_api(
    base64_image
):

    ready, error_message = (
        start_gemini_server_if_needed()
    )

    if not ready:

        return {

            "problem":
                "Gemini Error",

            "solution_type":
                "Error",

            "solution_text":
                error_message,

            "plottable_equation":
                "",

        }

    try:

        response = requests.post(

            GEMINI_SERVER_URL,

            json={
                "image":
                    base64_image
            },

            timeout=120,

        )

        try:

            payload = (
                response.json()
            )

        except ValueError:

            payload = {

                "problem":
                    "Gemini Error",

                "solution_type":
                    "Error",

                "solution_text":
                    (
                        "Gemini server returned "
                        f"HTTP "
                        f"{response.status_code}: "
                        f"{response.text[:500]}"
                    ),

                "plottable_equation":
                    "",

            }

        return payload

    except Exception as e:

        return {

            "problem":
                "Gemini Error",

            "solution_type":
                "Error",

            "solution_text":
                (
                    "Gemini server not reachable: "
                    f"{str(e)}"
                ),

            "plottable_equation":
                "",

        }


def solve_and_update_state(
    base64_image,
    input_mode
):

    set_state(

        analyzing=True,

        input_mode=input_mode,

        cooldown=False,

        drawing_active=True

    )

    api_response = (
        call_gemini_api(
            base64_image
        )
    )

    set_state(

        analyzing=False,

        drawing_canvas_b64=
            "",

        **api_response,

    )

    return api_response


def solve_and_update_state_async(
    base64_image,
    input_mode
):

    def worker():

        if not background_solve_lock.acquire(
            blocking=False
        ):

            return

        try:

            if get_state_copy().get(
                "analyzing"
            ):

                return

            solve_and_update_state(
                base64_image,
                input_mode=input_mode
            )

        finally:

            background_solve_lock.release()

    threading.Thread(

        target=worker,

        name="gesture-solve-thread",

        daemon=True,

    ).start()


# ==========================================================
# MAIN PAGE
# ==========================================================

@app.route("/")
def index():

    return render_template(
        "index.html"
    )


# ==========================================================
# STATUS
# ==========================================================

@app.route("/api/status")
def get_status():

    return jsonify(
        get_state_copy()
    )


# ==========================================================
# SOLVE DRAWING / UPLOAD
# ==========================================================

@app.route(
    "/api/solve",
    methods=["POST"]
)
def solve_mouse_canvas():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    image_b64 = (
        normalize_base64_image(
            data.get(
                "image",
                ""
            )
        )
    )

    if not image_b64:

        return jsonify({

            "error":
                "No image provided"

        }), 400

    requested_mode = data.get(
        "input_mode",
        "MOUSE"
    )

    solve_and_update_state(

        image_b64,

        input_mode=requested_mode

    )

    return jsonify(
        get_state_copy()
    )


# ==========================================================
# TEXT SOLVER
# ==========================================================

@app.route(
    "/api/solve-text",
    methods=["POST"]
)
def solve_text_input():

    data = (
        request.get_json(
            silent=True
        )
        or {}
    )

    problem_text = (

        data.get("problem")

        or

        data.get("equation")

        or ""

    )

    try:

        result = (
            solve_text_problem(
                problem_text
            )
        )

    except Exception as e:

        return jsonify({

            "error":
                str(e)

        }), 400

    set_state(

        analyzing=False,

        cooldown=False,

        input_mode="TEXT",

        drawing_active=True,

        drawing_canvas_b64="",

        **result,

    )

    return jsonify(
        get_state_copy()
    )


# ==========================================================
# CLEAR CANVAS
# ==========================================================

@app.route(
    "/api/clear",
    methods=["POST"]
)
def clear_canvas():

    with canvas_lock:

        drawing_canvas.fill(0)

    reset_solution_state()

    set_state(
        drawing_overlay_b64="",
        drawing_canvas_b64=""
    )

    return jsonify({

        "ok":
            True,

        "state":
            get_state_copy()

    })


# ==========================================================
# IMAGE ENCODING
# ==========================================================

def image_to_base64(img, quality=70):

    import cv2

    success, buffer = (
        cv2.imencode(
            ".jpg",
            img,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        )
    )

    if not success:

        return ""

    return (

        base64
        .b64encode(buffer)
        .decode("utf-8")

    )


def image_to_base64_scaled(img, width, height, quality=50):

    import cv2

    try:
        small = cv2.resize(img, (int(width), int(height)))
        return image_to_base64(small, quality=quality)
    except Exception:
        return ""


# ==========================================================
# HAND GESTURE SOLVE
# ==========================================================

@app.route(
    "/api/gesture/solve",
    methods=["POST"]
)
def solve_gesture_canvas():

    with canvas_lock:

        canvas_copy = drawing_canvas.copy()

    if not canvas_copy.any():

        return jsonify({

            "error":
                (
                    "Canvas is empty — "
                    "draw an equation first."
                )

        }), 400

    image_b64 = image_to_base64(canvas_copy)

    if not image_b64:

        return jsonify({

            "error":
                (
                    "Gesture drawing "
                    "is unavailable."
                )

        }), 400

    solve_and_update_state(

        image_b64,

        input_mode="CV"

    )

    return jsonify(
        get_state_copy()
    )


# ==========================================================
# MJPEG CAMERA STREAM
# ==========================================================

@app.route("/api/camera/feed")
def camera_feed():

    print("[CAMERA] Stream client connected", flush=True)

    def generate():

        global latest_frame_bytes

        consecutive_empty = 0

        while True:

            state = get_state_copy()

            if not state.get("camera_running"):
                break

            with frame_lock:

                frame_data = latest_frame_bytes

            if frame_data is None:

                consecutive_empty += 1

                if consecutive_empty > 200:
                    break

                time.sleep(0.01)

                continue

            consecutive_empty = 0

            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n"
                + frame_data
                + b"\r\n"
            )

            time.sleep(0.033)

        print("[CAMERA] Stream client disconnected", flush=True)

    return Response(

        stream_with_context(generate()),

        mimetype="multipart/x-mixed-replace; boundary=frame",

        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
        },

    )


# ==========================================================
# START CAMERA
# ==========================================================

@app.route(
    "/api/camera/start",
    methods=["POST"]
)
def start_camera():

    global cv_thread
    global latest_frame_bytes

    with cv_running_lock:

        state = get_state_copy()

        if state.get("camera_state") == "running":
            return jsonify({
                "ok": True,
                "message": "Camera is already running.",
                "state": state,
            })

        if state.get("camera_state") == "starting":
            return jsonify({
                "ok": True,
                "message": "Camera is starting.",
                "state": state,
            })

        if (
            cv_thread is not None
            and cv_thread.is_alive()
        ):

            cv_stop_event.set()

            cv_thread.join(
                timeout=3.0
            )

            cv_thread = None

            cv_stop_event.clear()

        print(
            "[CAMERA] Start requested",
            flush=True
        )

        cv_stop_event.clear()

        with frame_lock:

            latest_frame_bytes = None

        with canvas_lock:

            drawing_canvas.fill(0)

        set_state(

            input_mode="CV",

            camera_running=False,

            camera_state="starting",

            camera_error="",

            problem=
                DEFAULT_PROBLEM_PROMPT,

            solution_type="",

            solution_text="",

            drawing_canvas_b64="",

            cooldown=False,

        )

        cv_thread = threading.Thread(

            target=run_cv_loop,

            name=
                "gesture-camera-thread",

            daemon=True,

        )

        cv_thread.start()

    deadline = (
        time.time()
        + 25.0
    )

    while time.time() < deadline:

        state = (
            get_state_copy()
        )

        if state.get(
            "camera_running"
        ):

            return jsonify({

                "ok":
                    True,

                "message":
                    "Camera started.",

                "state":
                    state,

            })

        if state.get(
            "camera_error"
        ):

            return jsonify({

                "ok":
                    False,

                "error":
                    state[
                        "camera_error"
                    ],

                "state":
                    state,

            }), 500

        time.sleep(0.1)

    state = get_state_copy()

    return jsonify({

        "ok":
            False,

        "error":
            (
                "Camera did not become ready. "
                "Check terminal for "
                "[CAMERA ERROR]."
            ),

        "state":
            state,

    }), 500


# ==========================================================
# STOP CAMERA
# ==========================================================

@app.route(
    "/api/camera/stop",
    methods=["POST"]
)
def stop_camera():

    global cv_thread
    global latest_frame_bytes

    print(
        "[CAMERA] Stop requested",
        flush=True
    )

    set_state(
        camera_state="stopping"
    )

    cv_stop_event.set()

    thread = cv_thread

    if (
        thread is not None
        and thread.is_alive()
    ):

        thread.join(
            timeout=3.0
        )

    cv_thread = None

    cv_stop_event.clear()

    with frame_lock:

        latest_frame_bytes = None

    set_state(

        camera_running=False,

        camera_state="stopped",

        input_mode="MOUSE",

        cooldown=False,

        drawing_active=False,

    )

    return jsonify({

        "ok":
            True,

        "message":
            "Camera stopped.",

        "state":
            get_state_copy(),

    })


# ==========================================================
# MEDIAPIPE + COMPUTER VISION LOOP
# ==========================================================

def run_cv_loop():

    global latest_frame_bytes

    cap = None

    hands_detector = None

    camera_failed = False

    try:

        import cv2

        import traceback

        print(
            "[CAMERA] CV thread started",
            flush=True
        )

        index_tip_id = (

            mp_hands
            .HandLandmark
            .INDEX_FINGER_TIP

        )

        index_pip_id = (

            mp_hands
            .HandLandmark
            .INDEX_FINGER_PIP

        )

        middle_tip_id = (

            mp_hands
            .HandLandmark
            .MIDDLE_FINGER_TIP

        )

        middle_pip_id = (

            mp_hands
            .HandLandmark
            .MIDDLE_FINGER_PIP

        )

        thumb_tip_id = (

            mp_hands
            .HandLandmark
            .THUMB_TIP

        )

        thumb_ip_id = (

            mp_hands
            .HandLandmark
            .THUMB_IP

        )

        print(
            "[CAMERA] Opening webcam index 0",
            flush=True
        )

        if os.name == "nt":

            cap = cv2.VideoCapture(

                0,

                cv2.CAP_DSHOW

            )

            if not cap.isOpened():

                print(
                    "[CAMERA] DirectShow failed. "
                    "Trying default backend...",
                    flush=True
                )

                cap.release()

                cap = cv2.VideoCapture(0)

        else:

            cap = cv2.VideoCapture(0)

        if not cap.isOpened():

            raise RuntimeError(

                "Could not open webcam. "
                "Close Windows Camera, Teams, "
                "Zoom, Discord, OBS, or any "
                "other app using the webcam, "
                "then try again."

            )

        for prop, value in (

            (
                cv2.CAP_PROP_BUFFERSIZE,
                1
            ),

            (
                cv2.CAP_PROP_FRAME_WIDTH,
                CAMERA_WIDTH
            ),

            (
                cv2.CAP_PROP_FRAME_HEIGHT,
                CAMERA_HEIGHT
            ),

            (
                cv2.CAP_PROP_FPS,
                CAMERA_FPS
            ),

        ):

            try:

                cap.set(
                    prop,
                    value
                )

            except Exception:

                pass

        print(
            "[CAMERA] Webcam opened successfully",
            flush=True
        )

        frame_init = None

        for _ in range(40):

            success_init, candidate = cap.read()

            if (
                success_init
                and candidate is not None
            ):

                frame_init = cv2.flip(
                    candidate,
                    1
                )

                break

            if cv_stop_event.is_set():

                return

            time.sleep(0.025)

        if frame_init is None:

            raise RuntimeError(

                "Webcam opened but did not "
                "return frames. Try unplugging "
                "and reconnecting the camera."

            )

        initial_stream_frame = cv2.resize(

            frame_init,

            (
                CANVAS_SIZE,
                CANVAS_SIZE
            )

        )

        success_enc, buf = cv2.imencode(

            ".jpg",

            initial_stream_frame,

            [
                int(cv2.IMWRITE_JPEG_QUALITY),
                68
            ]

        )

        if success_enc:

            with frame_lock:

                latest_frame_bytes = (
                    buf.tobytes()
                )

        set_state(

            input_mode="CV",

            camera_running=True,

            camera_state="running",

            camera_error="",

            drawing_active=False,

            camera_frame_b64="",

            drawing_overlay_b64="",

            drawing_canvas_b64="",

        )

        print(
            "[CAMERA] Initializing MediaPipe Hands",
            flush=True
        )

        hands_detector = (
            mp_hands.Hands(

                static_image_mode=False,

                max_num_hands=1,

                model_complexity=0,

                min_detection_confidence=
                    0.55,

                min_tracking_confidence=
                    0.45,

            )
        )

        print(
            "[CAMERA] MediaPipe initialized",
            flush=True
        )

        last_point = None

        smoothed_point = None

        prev_thumb_up = False

        cooldown_counter = 0

        PEN_UP_DEBOUNCE = 5
        pen_up_counter = 0

        stream_interval = (
            1.0
            /
            STREAM_FPS
        )

        last_stream_time = 0.0

        last_state_time = 0.0

        last_results = None

        print(
            "[CAMERA] First frame expected soon",
            flush=True
        )

        while (
            cap.isOpened()
            and not cv_stop_event.is_set()
        ):

            success, frame = (
                cap.read()
            )

            if not success:

                time.sleep(0.03)

                continue

            frame = cv2.flip(
                frame,
                1
            )

            h, w, _ = (
                frame.shape
            )

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

            rgb.flags.writeable = False

            try:
                results = (
                    hands_detector.process(rgb)
                )
            except Exception:
                results = last_results

            last_results = results

            current_point = None
            thumb_up = False
            drawing_gesture = False

            if (
                results
                and getattr(
                    results,
                    "multi_hand_landmarks",
                    None
                )
            ):

                landmarks = (
                    results
                    .multi_hand_landmarks[0]
                    .landmark
                )

                index_up = (

                    landmarks[
                        index_tip_id
                    ].y

                    <

                    landmarks[
                        index_pip_id
                    ].y

                )

                middle_up = (

                    landmarks[
                        middle_tip_id
                    ].y

                    <

                    landmarks[
                        middle_pip_id
                    ].y

                )

                drawing_gesture = (
                    index_up and not middle_up
                )

                scale = min(
                    CANVAS_SIZE / w,
                    CANVAS_SIZE / h
                )

                pad_x = (
                    CANVAS_SIZE - w * scale
                ) / 2

                pad_y = (
                    CANVAS_SIZE - h * scale
                ) / 2

                raw_x = int(
                    landmarks[
                        index_tip_id
                    ].x
                    * w
                    * scale
                    + pad_x
                )

                raw_y = int(
                    landmarks[
                        index_tip_id
                    ].y
                    * h
                    * scale
                    + pad_y
                )

                if drawing_gesture:

                    pen_up_counter = 0

                    if smoothed_point is None:

                        smoothed_point = (
                            raw_x,
                            raw_y
                        )

                    else:

                        sx, sy = smoothed_point

                        smoothed_point = (

                            int(
                                sx * (1 - 0.6)
                                + raw_x * 0.6
                            ),

                            int(
                                sy * (1 - 0.6)
                                + raw_y * 0.6
                            )

                        )

                    current_point = smoothed_point

                else:

                    pen_up_counter += 1

                    if pen_up_counter >= PEN_UP_DEBOUNCE:

                        last_point = None

                        smoothed_point = None

                thumb_up = (

                    landmarks[
                        thumb_tip_id
                    ].y

                    <

                    landmarks[
                        thumb_ip_id
                    ].y

                    - 0.04

                    and

                    not index_up

                )

                if (

                    thumb_up

                    and

                    not prev_thumb_up

                    and

                    cooldown_counter == 0

                ):

                    with canvas_lock:

                        canvas_for_solve = (
                            drawing_canvas.copy()
                        )

                    if canvas_for_solve.any():

                        base64_img = (
                            image_to_base64(
                                canvas_for_solve
                            )
                        )

                    else:

                        base64_img = ""

                    if base64_img:

                        print(

                            "[CAMERA] "
                            "Thumb solve gesture detected",

                            flush=True

                        )

                        cooldown_counter = (
                            COOLDOWN_FRAMES
                        )

                        solve_and_update_state_async(

                            base64_img,

                            input_mode="CV"

                        )

            else:

                last_point = None

                smoothed_point = None

                pen_up_counter = 0

            prev_thumb_up = (
                thumb_up
            )

            if current_point is not None:

                if last_point is not None:

                    with canvas_lock:

                        cv2.line(

                            drawing_canvas,

                            (
                                int(last_point[0]),
                                int(last_point[1])
                            ),

                            (
                                int(current_point[0]),
                                int(current_point[1])
                            ),

                            LINE_COLOR,

                            LINE_THICKNESS,

                        )

                last_point = current_point

            if cooldown_counter > 0:

                cooldown_counter -= 1

            now = time.time()

            if (
                now - last_stream_time
                >= stream_interval
            ):

                last_stream_time = now

                try:

                    with canvas_lock:

                        canvas_copy_stream = (
                            drawing_canvas.copy()
                        )

                    stream_frame = cv2.resize(
                        frame,
                        (
                            CANVAS_SIZE,
                            CANVAS_SIZE,
                        )
                    )

                    drawing_mask = (
                        canvas_copy_stream.any(axis=2)
                    )

                    stream_frame[drawing_mask] = (
                        canvas_copy_stream[drawing_mask]
                    )

                    if (
                        current_point is not None
                        and drawing_gesture
                    ):

                        cx = int(
                            current_point[0]
                        )

                        cy = int(
                            current_point[1]
                        )

                        cv2.circle(
                            stream_frame,
                            (cx, cy),
                            10,
                            (0, 255, 100),
                            -1
                        )

                    success_enc, buf = cv2.imencode(
                        ".jpg",
                        stream_frame,
                        [
                            int(cv2.IMWRITE_JPEG_QUALITY),
                            68
                        ]
                    )

                    if success_enc:

                        with frame_lock:

                            latest_frame_bytes = (
                                buf.tobytes()
                            )

                except Exception:

                    pass

            if (
                now - last_state_time
                >= CAMERA_STATE_INTERVAL
            ):

                last_state_time = now

                set_state(

                    input_mode="CV",

                    camera_running=True,

                    camera_state="running",

                    camera_error="",

                    drawing_active=
                        drawing_gesture,

                    cooldown=(
                        cooldown_counter > 0
                    ),

                    camera_frame_b64="",

                )

            time.sleep(0.005)

    except Exception as exc:

        import traceback

        camera_failed = True

        error_message = (

            f"{type(exc).__name__}: "
            f"{exc}"

        )

        print(

            f"[CAMERA ERROR] "
            f"{error_message}",

            flush=True

        )

        traceback.print_exc()

        set_state(

            camera_running=False,

            camera_state="error",

            camera_error=
                error_message,

            input_mode="CV",

            drawing_active=False,

        )

    finally:

        if cap is not None:

            try:

                cap.release()

            except Exception:

                pass

        if hands_detector is not None:

            try:

                hands_detector.close()

            except Exception:

                pass

        if not camera_failed:

            set_state(

                camera_running=False,

                camera_state="stopped",

                drawing_active=False

            )

        with frame_lock:

            latest_frame_bytes = None

        print(

            "[CAMERA] Webcam released",

            flush=True

        )


# ==========================================================
# RUN SERVER
# ==========================================================

def run_flask():

    app.run(

        host="0.0.0.0",

        port=5000,

        debug=False,

        use_reloader=False,

        threaded=True,

    )


def main():

    run_flask()


if __name__ == "__main__":

    main()
