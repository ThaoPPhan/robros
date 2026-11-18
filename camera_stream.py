
from flask import Flask, Response
from picamera2 import Picamera2
import cv2
import time

app = Flask(__name__)

# Initialize Raspberry Pi camera
camera = Picamera2()
camera.configure(
    camera.create_video_configuration(
        main={"size": (640, 480), "format": "RGB888"}
    )
)
camera.start()
time.sleep(2)


def generate_frames():
    while True:
        frame = camera.capture_array()

        # Encode frame as JPEG
        success, buffer = cv2.imencode(
            ".jpg",
            frame,
            [cv2.IMWRITE_JPEG_QUALITY, 80]
        )

        if not success:
            continue

        # Stream frame to browser
        yield (
            b"--frame\r\n"
            b"Content-Type: image/jpeg\r\n\r\n"
            + buffer.tobytes()
            + b"\r\n"
        )


@app.route("/")
def index():
    return """
    <html>
      <head>
        <title>Robros Camera</title>
      </head>
      <body style="background:#151515; color:white;
                   text-align:center; font-family:Arial;">
        <h2>Robros - Live Camera</h2>
        <img src="/video_feed" style="width:80%; max-width:900px;">
      </body>
    </html>
    """


@app.route("/video_feed")
def video_feed():
    return Response(
        generate_frames(),
        mimetype="multipart/x-mixed-replace; boundary=frame"
    )


if __name__ == "__main__":
    try:
        app.run(
            host="0.0.0.0",
            port=5000,
            threaded=True
        )
    finally:
        camera.stop()
