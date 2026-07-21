// ==========================================================
// ELEMENTS


const statusBadge =
    document.getElementById("statusBadge");

const statusText =
    document.getElementById("statusText");

const modeBadge =
    document.getElementById("modeBadge");

const problemText =
    document.getElementById("problemText");

const typeBadge =
    document.getElementById("typeBadge");

const solutionDisplay =
    document.getElementById("solutionDisplay");

const errorBanner =
    document.getElementById("errorBanner");

const errorBannerText =
    document.getElementById("errorBannerText");


// MODE BUTTONS

const mouseModeButton =
    document.getElementById("mouseModeButton");

const gestureModeButton =
    document.getElementById("gestureModeButton");

const uploadModeButton =
    document.getElementById("uploadModeButton");

const textModeButton =
    document.getElementById("textModeButton");


// SOLVE-CURRENT (persistent action bar above the mode panels)

const solveCurrentButton =
    document.getElementById("solveCurrentButton");


// MODE SECTIONS

const mouseModeSection =
    document.getElementById("mouseModeSection");

const gestureModeSection =
    document.getElementById("gestureModeSection");

const uploadModeSection =
    document.getElementById("uploadModeSection");

const textModeSection =
    document.getElementById("textModeSection");


// MOUSE

const mouseCanvas =
    document.getElementById("mouseCanvas");

const solveButton =
    document.getElementById("solveButton");

const clearButton =
    document.getElementById("clearButton");

const drawingStatus =
    document.getElementById("drawingStatus");

const canvasPlaceholder =
    document.getElementById("canvasPlaceholder");


// CAMERA

const startCameraButton =
    document.getElementById("startCameraButton");

const stopCameraButton =
    document.getElementById("stopCameraButton");

const solveGestureButton =
    document.getElementById("solveGestureButton");

const clearGestureButton =
    document.getElementById("clearGestureButton");

const gestureCanvasImage =
    document.getElementById("gestureCanvasImage");

const gestureOverlayImage =
    document.getElementById("gestureOverlayImage");

const gesturePlaceholder =
    document.getElementById("gesturePlaceholder");

const gestureStatus =
    document.getElementById("gestureStatus");


// UPLOAD

const imageUploadInput =
    document.getElementById("imageUploadInput");

const chooseImageButton =
    document.getElementById("chooseImageButton");

const uploadDropZone =
    document.getElementById("uploadDropZone");

const uploadPreviewContainer =
    document.getElementById(
        "uploadPreviewContainer"
    );

const uploadPreview =
    document.getElementById("uploadPreview");

const removeUploadButton =
    document.getElementById("removeUploadButton");

const solveUploadButton =
    document.getElementById("solveUploadButton");


// TEXT

const equationInput =
    document.getElementById("equationInput");

const solveTextButton =
    document.getElementById("solveTextButton");


// ==========================================================
// STATE


let currentMode =
    "MOUSE";

let uploadedImageBase64 =
    "";

let isDrawing =
    false;

let cameraStarted =
    false;

let solving =
    false;

let gestureStreamActive =
    false;


// ==========================================================
// CANVAS SETUP


const ctx =
    mouseCanvas.getContext("2d");


ctx.fillStyle =
    "#000000";

ctx.fillRect(
    0,
    0,
    mouseCanvas.width,
    mouseCanvas.height
);


ctx.strokeStyle =
    "#ffffff";

ctx.lineWidth =
    8;

ctx.lineCap =
    "round";

ctx.lineJoin =
    "round";


// ==========================================================
// HELPERS


function showError(
    message
) {

    if (!errorBanner) {

        return;

    }


    const textTarget =
        errorBannerText
        ||
        errorBanner;


    textTarget.textContent =
        message;


    errorBanner.style.display =
        "flex";


    setTimeout(
        () => {

            errorBanner.style.display =
                "none";

        },
        5000
    );

}


function setStatus(
    text,
    state = "ready"
) {

    statusText.textContent =
        text;


    statusBadge.className =
        "status-badge";


    if (
        state ===
        "analyzing"
    ) {

        statusBadge.classList.add(
            "status-analyzing"
        );

    }

    else if (
        state ===
        "error"
    ) {

        statusBadge.classList.add(
            "status-error"
        );

    }

    else if (
        state ===
        "cooldown"
    ) {

        statusBadge.classList.add(
            "status-cooldown"
        );

    }

    else {

        statusBadge.classList.add(
            "status-ready"
        );

    }

}


// ==========================================================
// SOLUTION DISPLAY


function escapeHtml(
    value
) {

    return String(
        value ?? ""
    )

        .replaceAll(
            "&",
            "&amp;"
        )

        .replaceAll(
            "<",
            "&lt;"
        )

        .replaceAll(
            ">",
            "&gt;"
        )

        .replaceAll(
            '"',
            "&quot;"
        )

        .replaceAll(
            "'",
            "&#039;"
        );

}


function renderSolution(
    text
) {

    if (!text) {

        solutionDisplay.innerHTML = `

            <div class="empty-solution">

                <div class="thinking-bars">

                    <i></i>
                    <i></i>
                    <i></i>

                </div>

                <strong>
                    Your solution will appear here
                </strong>

                <p>
                    Choose an input method and submit
                    a problem to begin.
                </p>

            </div>

        `;

        return;

    }


    const lines =
        String(text)

            .split("\n")

            .map(
                line =>
                    line.trim()
            )

            .filter(Boolean);


    if (
        lines.length ===
        0
    ) {

        solutionDisplay.textContent =
            text;

        return;

    }


    solutionDisplay.innerHTML =
        `

        <div class="solution-steps">

            ${
                lines.map(
                    (
                        line,
                        index
                    ) => {

                        return `

                            <div class="step-item">

                                <div class="step-label">

                                    ${
                                        index === 0
                                            ?
                                            "Result"
                                            :
                                            `Step ${index}`
                                    }

                                </div>

                                <div class="step-content">

                                    ${escapeHtml(line)}

                                </div>

                            </div>

                        `;

                    }
                ).join("")
            }

        </div>

        `;

}


// ==========================================================
// APPLY BACKEND STATE
// ==========================================================

function applyState(
    state
) {

    if (!state) {

        return;

    }


    if (
        state.analyzing
    ) {

        setStatus(
            "ANALYZING",
            "analyzing"
        );

    }

    else if (
        state.camera_error
    ) {

        setStatus(
            "CAMERA ERROR",
            "error"
        );

    }

    else if (
        state.cooldown
    ) {

        setStatus(
            "COOLDOWN",
            "cooldown"
        );

    }

    else {

        setStatus(
            "READY",
            "ready"
        );

    }


    if (
        state.problem
    ) {

        problemText.textContent =
            state.problem;

    }


    if (
        state.solution_type
    ) {

        typeBadge.textContent =
            state.solution_type;

        typeBadge.style.display =
            "inline-block";

    }

    else {

        typeBadge.style.display =
            "none";

    }


    renderSolution(
        state.solution_text
    );


    if (
        currentMode ===
        "CV"
    ) {

        updateCameraUI(
            state
        );

    }

}


// ==========================================================
// MODE SELECTION
// ==========================================================

function hideAllModes() {

    mouseModeSection.style.display =
        "none";

    gestureModeSection.style.display =
        "none";

    uploadModeSection.style.display =
        "none";

    textModeSection.style.display =
        "none";

}


function clearModeButtons() {

    [
        mouseModeButton,
        gestureModeButton,
        uploadModeButton,
        textModeButton
    ]

        .forEach(
            button => {

                button.classList.remove(
                    "active"
                );

                button.setAttribute(
                    "aria-selected",
                    "false"
                );

            }
        );

}


function selectInputMode(
    mode
) {

    currentMode =
        mode;


    hideAllModes();

    clearModeButtons();


    if (
        mode ===
        "MOUSE"
    ) {

        mouseModeSection.style.display =
            "block";

        mouseModeButton.classList.add(
            "active"
        );

        mouseModeButton.setAttribute(
            "aria-selected",
            "true"
        );

        modeBadge.textContent =
            "MOUSE";

    }


    else if (
        mode ===
        "CV"
    ) {

        gestureModeSection.style.display =
            "block";

        gestureModeButton.classList.add(
            "active"
        );

        gestureModeButton.setAttribute(
            "aria-selected",
            "true"
        );

        modeBadge.textContent =
            "GESTURE";

    }


    else if (
        mode ===
        "UPLOAD"
    ) {

        uploadModeSection.style.display =
            "block";

        uploadModeButton.classList.add(
            "active"
        );

        uploadModeButton.setAttribute(
            "aria-selected",
            "true"
        );

        modeBadge.textContent =
            "UPLOAD";

    }


    else if (
        mode ===
        "TEXT"
    ) {

        textModeSection.style.display =
            "block";

        textModeButton.classList.add(
            "active"
        );

        textModeButton.setAttribute(
            "aria-selected",
            "true"
        );

        modeBadge.textContent =
            "TEXT";


        setTimeout(
            () => {

                equationInput.focus();

            },
            100
        );

    }

}


// ==========================================================
// MODE BUTTON EVENTS
// ==========================================================

mouseModeButton.addEventListener(
    "click",
    () => {

        selectInputMode(
            "MOUSE"
        );

    }
);


gestureModeButton.addEventListener(
    "click",
    () => {

        selectInputMode(
            "CV"
        );

    }
);


uploadModeButton.addEventListener(
    "click",
    () => {

        selectInputMode(
            "UPLOAD"
        );

    }
);


textModeButton.addEventListener(
    "click",
    () => {

        selectInputMode(
            "TEXT"
        );

    }
);


// ==========================================================
// MOUSE DRAWING
// ==========================================================

function getCanvasPosition(
    event
) {

    const rect =
        mouseCanvas.getBoundingClientRect();


    const scaleX =
        mouseCanvas.width
        /
        rect.width;


    const scaleY =
        mouseCanvas.height
        /
        rect.height;


    return {

        x:
            (
                event.clientX
                -
                rect.left
            )
            *
            scaleX,

        y:
            (
                event.clientY
                -
                rect.top
            )
            *
            scaleY

    };

}


function startDrawing(
    event
) {

    if (
        event.button !== undefined
        &&
        event.button !== 0
    ) {

        return;

    }


    isDrawing =
        true;


    if (
        canvasPlaceholder
    ) {

        canvasPlaceholder.style.display =
            "none";

    }


    const position =
        getCanvasPosition(
            event
        );


    ctx.beginPath();

    ctx.moveTo(
        position.x,
        position.y
    );

}


function draw(
    event
) {

    if (
        !isDrawing
    ) {

        return;

    }


    const position =
        getCanvasPosition(
            event
        );


    ctx.lineTo(
        position.x,
        position.y
    );


    ctx.stroke();


    ctx.beginPath();


    ctx.moveTo(
        position.x,
        position.y
    );

}


function stopDrawing() {

    if (
        !isDrawing
    ) {

        return;

    }


    isDrawing =
        false;


    ctx.beginPath();

}


mouseCanvas.addEventListener(
    "mousedown",
    startDrawing
);


mouseCanvas.addEventListener(
    "mousemove",
    draw
);


mouseCanvas.addEventListener(
    "mouseup",
    stopDrawing
);


mouseCanvas.addEventListener(
    "mouseleave",
    stopDrawing
);


// Touch / pointer support

mouseCanvas.addEventListener(
    "pointerdown",
    event => {

        if (
            event.pointerType ===
            "mouse"
        ) {

            return;

        }


        event.preventDefault();

        startDrawing(
            event
        );

    }
);


mouseCanvas.addEventListener(
    "pointermove",
    event => {

        if (
            event.pointerType ===
            "mouse"
        ) {

            return;

        }


        event.preventDefault();

        draw(
            event
        );

    }
);


mouseCanvas.addEventListener(
    "pointerup",
    event => {

        if (
            event.pointerType !==
            "mouse"
        ) {

            stopDrawing();

        }

    }
);


// ==========================================================
// CLEAR MOUSE CANVAS
// ==========================================================

async function clearDrawing() {

    ctx.fillStyle =
        "#000000";


    ctx.fillRect(
        0,
        0,
        mouseCanvas.width,
        mouseCanvas.height
    );


    if (
        canvasPlaceholder
    ) {

        canvasPlaceholder.style.display =
            "flex";

    }


    try {

        await fetch(
            "/api/clear",
            {
                method:
                    "POST"
            }
        );

    }

    catch (
        error
    ) {

        console.error(
            error
        );

    }


    problemText.textContent =
        "Waiting for input...";


    typeBadge.style.display =
        "none";


    renderSolution(
        ""
    );

}


clearButton.addEventListener(
    "click",
    clearDrawing
);


// ==========================================================
// SOLVE MOUSE CANVAS
// ==========================================================

async function solveMouseDrawing() {

    if (
        solving
    ) {

        return;

    }


    solving =
        true;


    solveButton.disabled =
        true;


    setStatus(
        "ANALYZING",
        "analyzing"
    );


    try {

        const image =
            mouseCanvas.toDataURL(
                "image/png"
            );


        const response =
            await fetch(

                "/api/solve",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            image:
                                image,

                            input_mode:
                                "MOUSE"

                        })

                }

            );


        const data =
            await response.json();


        if (
            !response.ok
        ) {

            throw new Error(

                data.error
                ||
                "Could not solve drawing."

            );

        }


        applyState(
            data
        );

    }

    catch (
        error
    ) {

        showError(
            error.message
        );


        setStatus(
            "ERROR",
            "error"
        );

    }

    finally {

        solving =
            false;


        solveButton.disabled =
            false;

    }

}


solveButton.addEventListener(
    "click",
    solveMouseDrawing
);


// ==========================================================
// UPLOAD IMAGE
// ==========================================================

chooseImageButton.addEventListener(
    "click",
    () => {

        imageUploadInput.click();

    }
);


imageUploadInput.addEventListener(
    "change",
    () => {

        const file =
            imageUploadInput.files[0];


        if (
            !file
        ) {

            return;

        }


        loadUploadedFile(
            file
        );

    }
);


function loadUploadedFile(
    file
) {

    if (
        !file.type.startsWith(
            "image/"
        )
    ) {

        showError(
            "Please select an image file."
        );

        return;

    }


    const reader =
        new FileReader();


    reader.onload =
        event => {

            uploadedImageBase64 =
                event.target.result;


            uploadPreview.src =
                uploadedImageBase64;


            uploadPreview.style.display =
                "block";


            uploadPreviewContainer.style.display =
                "block";


            uploadDropZone.style.display =
                "none";

        };


    reader.readAsDataURL(
        file
    );

}


// ==========================================================
// DRAG & DROP
// ==========================================================

[
    "dragenter",
    "dragover"
]

    .forEach(
        eventName => {

            uploadDropZone.addEventListener(

                eventName,

                event => {

                    event.preventDefault();

                    uploadDropZone.classList.add(
                        "dragover"
                    );

                }

            );

        }
    );


[
    "dragleave",
    "drop"
]

    .forEach(
        eventName => {

            uploadDropZone.addEventListener(

                eventName,

                event => {

                    event.preventDefault();

                    uploadDropZone.classList.remove(
                        "dragover"
                    );

                }

            );

        }
    );


uploadDropZone.addEventListener(
    "drop",
    event => {

        const file =
            event.dataTransfer
            ?.files
            ?.[0];


        if (
            file
        ) {

            loadUploadedFile(
                file
            );

        }

    }
);


// ==========================================================
// REMOVE UPLOAD
// ==========================================================

removeUploadButton.addEventListener(
    "click",
    () => {

        uploadedImageBase64 =
            "";


        imageUploadInput.value =
            "";


        uploadPreview.src =
            "";


        uploadPreview.style.display =
            "none";


        uploadPreviewContainer.style.display =
            "none";


        uploadDropZone.style.display =
            "flex";

    }
);


// ==========================================================
// SOLVE UPLOAD
// ==========================================================

solveUploadButton.addEventListener(
    "click",
    async () => {

        if (
            !uploadedImageBase64
        ) {

            showError(
                "Choose an image first."
            );

            return;

        }


        if (
            solving
        ) {

            return;

        }


        solving =
            true;


        solveUploadButton.disabled =
            true;


        setStatus(
            "ANALYZING",
            "analyzing"
        );


        try {

            const response =
                await fetch(

                    "/api/solve",

                    {

                        method:
                            "POST",

                        headers: {

                            "Content-Type":
                                "application/json"

                        },

                        body:
                            JSON.stringify({

                                image:
                                    uploadedImageBase64,

                                input_mode:
                                    "UPLOAD"

                            })

                    }

                );


            const data =
                await response.json();


            if (
                !response.ok
            ) {

                throw new Error(

                    data.error
                    ||
                    "Could not solve image."

                );

            }


            applyState(
                data
            );

        }

        catch (
            error
        ) {

            showError(
                error.message
            );


            setStatus(
                "ERROR",
                "error"
            );

        }

        finally {

            solving =
                false;


            solveUploadButton.disabled =
                false;

        }

    }
);


// ==========================================================
// TEXT SOLVER
// ==========================================================

async function solveText() {

    const equation =
        equationInput.value.trim();


    if (
        !equation
    ) {

        showError(
            "Enter an equation first."
        );

        return;

    }


    if (
        solving
    ) {

        return;

    }


    solving =
        true;


    solveTextButton.disabled =
        true;


    setStatus(
        "ANALYZING",
        "analyzing"
    );


    try {

        const response =
            await fetch(

                "/api/solve-text",

                {

                    method:
                        "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            equation:
                                equation

                        })

                }

            );


        const data =
            await response.json();


        if (
            !response.ok
        ) {

            throw new Error(

                data.error
                ||
                "Could not solve equation."

            );

        }


        applyState(
            data
        );

    }

    catch (
        error
    ) {

        showError(
            error.message
        );


        setStatus(
            "ERROR",
            "error"
        );

    }

    finally {

        solving =
            false;


        solveTextButton.disabled =
            false;

    }

}


solveTextButton.addEventListener(
    "click",
    solveText
);


equationInput.addEventListener(
    "keydown",
    event => {

        if (
            event.key ===
            "Enter"
        ) {

            solveText();

        }

    }
);


// Example equations

document
    .querySelectorAll(
        "[data-equation]"
    )
    .forEach(
        button => {

            button.addEventListener(
                "click",
                () => {

                    equationInput.value =
                        button.dataset.equation;

                    equationInput.focus();

                }
            );

        }
    );


// ==========================================================
// SOLVE-CURRENT (persistent action bar)
//
// Previously a dead button with no handler. Wired here to
// trigger the correct solve action for whichever input mode
// is currently active, without altering any mode's own
// solve behavior.
// ==========================================================

if (
    solveCurrentButton
) {

    solveCurrentButton.addEventListener(
        "click",
        () => {

            if (
                currentMode ===
                "MOUSE"
            ) {

                solveMouseDrawing();

            }

            else if (
                currentMode ===
                "CV"
            ) {

                if (
                    !cameraStarted
                ) {

                    showError(
                        "Start the camera first."
                    );

                    return;

                }


                solveGestureButton.click();

            }

            else if (
                currentMode ===
                "UPLOAD"
            ) {

                solveUploadButton.click();

            }

            else if (
                currentMode ===
                "TEXT"
            ) {

                solveText();

            }

        }
    );

}


// ==========================================================
// CAMERA UI
// ==========================================================

function startGestureStream() {

    if (
        gestureStreamActive
        &&
        gestureCanvasImage.getAttribute(
            "src"
        )
    ) {

        return;

    }


    gestureStreamActive =
        true;


    gestureCanvasImage.src =
        "/api/camera/feed?t="
        +
        Date.now();

}


function stopGestureStream() {

    gestureStreamActive =
        false;


    gestureCanvasImage.removeAttribute(
        "src"
    );

}


function updateCameraUI(
    state
) {

    const running =
        Boolean(
            state.camera_running
        );

    const starting =
        state.camera_state ===
        "starting";


    cameraStarted =
        running;


    startCameraButton.disabled =
        running
        ||
        starting;


    stopCameraButton.disabled =
        !running
        &&
        !starting;


    if (
        running
    ) {

        gesturePlaceholder.style.display =
            "none";


        gestureCanvasImage.style.display =
            "block";


        startGestureStream();


        gestureOverlayImage.style.display =
            "none";


        gestureOverlayImage.removeAttribute(
            "src"
        );


        gestureStatus.textContent =
            state.drawing_active
            ?
            "Drawing active"
            :
            "Camera running";


        gestureStatus.className =
            state.drawing_active
            ?
            "panel-note drawing-on"
            :
            "panel-note drawing-off";


    }

    else {

        stopGestureStream();


        gestureCanvasImage.style.display =
            "none";


        gestureOverlayImage.style.display =
            "none";


        gesturePlaceholder.style.display =
            "flex";


        gestureStatus.textContent =
            state.camera_error
            ?
            state.camera_error
            :
            (
                starting
                ?
                "Starting camera..."
                :
                "Camera stopped"
            );


        gestureStatus.className =
            "panel-note drawing-off";

    }

}


// ==========================================================
// START CAMERA
// ==========================================================

startCameraButton.addEventListener(
    "click",
    async () => {

        startCameraButton.disabled =
            true;


        gestureStatus.textContent =
            "Starting camera...";


        setStatus(
            "STARTING CAMERA",
            "analyzing"
        );


        try {

            const response =
                await fetch(

                    "/api/camera/start",

                    {

                        method:
                            "POST"

                    }

                );


            const data =
                await response.json();


            if (
                !response.ok
                ||
                data.ok === false
            ) {

                throw new Error(

                    data.error
                    ||
                    "Could not start camera."

                );

            }


            const state =
                data.state
                ||
                data;


            applyState(
                state
            );


            cameraStarted =
                true;


            gesturePlaceholder.style.display =
                "none";


            gestureCanvasImage.style.display =
                "block";


            startGestureStream();


            startCameraButton.disabled =
                true;


            stopCameraButton.disabled =
                false;


            gestureStatus.textContent =
                "Camera running";


            setStatus(
                "READY",
                "ready"
            );

        }

        catch (
            error
        ) {

            cameraStarted =
                false;


            stopGestureStream();


            startCameraButton.disabled =
                false;


            stopCameraButton.disabled =
                true;


            gestureStatus.textContent =
                error.message;


            showError(
                error.message
            );


            setStatus(
                "CAMERA ERROR",
                "error"
            );

        }

    }
);


// ==========================================================
// STOP CAMERA
// ==========================================================

stopCameraButton.addEventListener(
    "click",
    async () => {

        try {

            const response =
                await fetch(

                    "/api/camera/stop",

                    {

                        method:
                            "POST"

                    }

                );


            const data =
                await response.json();


            cameraStarted =
                false;


            stopGestureStream();


            gestureCanvasImage.style.display =
                "none";


            gestureOverlayImage.style.display =
                "none";


            gesturePlaceholder.style.display =
                "flex";


            startCameraButton.disabled =
                false;


            stopCameraButton.disabled =
                true;


            gestureStatus.textContent =
                "Camera stopped";


            if (
                data.state
            ) {

                applyState(
                    data.state
                );

            }

        }

        catch (
            error
        ) {

            showError(
                error.message
            );

        }

    }
);


// ==========================================================
// CLEAR GESTURE CANVAS
// ==========================================================

clearGestureButton.addEventListener(
    "click",
    async () => {

        try {

            const response =
                await fetch(

                    "/api/clear",

                    {

                        method:
                            "POST"

                    }

                );


            const data =
                await response.json();


            gestureOverlayImage.src =
                "";


            gestureOverlayImage.removeAttribute(
                "src"
            );


            gestureOverlayImage.style.display =
                "none";


            problemText.textContent =
                "Waiting for input...";


            typeBadge.style.display =
                "none";


            renderSolution(
                ""
            );


            if (
                data.state
            ) {

                applyState(
                    data.state
                );

            }

        }

        catch (
            error
        ) {

            showError(
                error.message
            );

        }

    }
);


// ==========================================================
// SOLVE GESTURE
// ==========================================================

solveGestureButton.addEventListener(
    "click",
    async () => {

        if (
            solving
        ) {

            return;

        }


        solving =
            true;


        solveGestureButton.disabled =
            true;


        setStatus(
            "ANALYZING",
            "analyzing"
        );


        try {

            const response =
                await fetch(

                    "/api/gesture/solve",

                    {

                        method:
                            "POST"

                    }

                );


            const data =
                await response.json();


            if (
                !response.ok
            ) {

                throw new Error(

                    data.error
                    ||
                    "Could not solve gesture drawing."

                );

            }


            applyState(
                data
            );

        }

        catch (
            error
        ) {

            showError(
                error.message
            );


            setStatus(
                "ERROR",
                "error"
            );

        }

        finally {

            solving =
                false;


            solveGestureButton.disabled =
                false;

        }

    }
);


// ==========================================================
// STATUS POLLING
// ==========================================================

async function pollStatus() {

    try {

        const response =
            await fetch(
                "/api/status",
                {
                    cache:
                        "no-store"
                }
            );


        if (
            !response.ok
        ) {

            return;

        }


        const state =
            await response.json();


        if (
            state.analyzing
        ) {

            setStatus(
                "ANALYZING",
                "analyzing"
            );

        }

        else if (
            state.camera_error
        ) {

            setStatus(
                "CAMERA ERROR",
                "error"
            );

        }

        else {

            setStatus(
                "READY",
                "ready"
            );

        }


        if (
            currentMode ===
            "CV"
        ) {

            updateCameraUI(
                state
            );

        }


        if (
            state.problem
            &&
            state.problem !==
            "Draw a math problem (e.g., solve for x: 2x+3=7)"
        ) {

            problemText.textContent =
                state.problem;

        }


        if (
            state.solution_text
        ) {

            renderSolution(
                state.solution_text
            );

        }


        if (
            state.solution_type
        ) {

            typeBadge.textContent =
                state.solution_type;

            typeBadge.style.display =
                "inline-block";

        }

    }

    catch (
        error
    ) {

        console.error(
            "Status polling error:",
            error
        );

    }

}


// Polling intentionally slower than old version.
// Old ~250ms polling unnecessarily spammed Flask.

setInterval(
    pollStatus,
    1000
);


// ==========================================================
// INITIALIZE
// ==========================================================

function initializeApp() {

    selectInputMode(
        "MOUSE"
    );


    renderSolution(
        ""
    );


    setStatus(
        "READY",
        "ready"
    );


    pollStatus();

}


initializeApp();