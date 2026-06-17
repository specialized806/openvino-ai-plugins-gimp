import warnings

# Suppress mediapipe warning from controlnet_aux when it's not installed
# mediapipe is an optional dependency for controlnet_aux but not used in our pipeline
warnings.filterwarnings(
    "ignore",
    message=".*The module 'mediapipe' is not installed.*",
    category=UserWarning
)
