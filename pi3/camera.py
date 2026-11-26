"""Camera frame source: Pi Camera (picamera2) or a USB camera (cv2.VideoCapture).
Backend picked by pi3/config.yaml's camera.backend.

Constructing a Camera touches no hardware (safe to import/instantiate on the
laptop); start() and read_frame() do, so the matching libraries are imported
there instead of at module level.
"""


class Camera:
    def __init__(self, backend: str, size, usb_index: int = 0):
        self.backend = backend
        self.size = tuple(size)
        self.usb_index = usb_index
        self._picam = None
        self._cap = None

    def start(self) -> None:
        if self.backend == "picamera2":
            from picamera2 import Picamera2  # hardware: only importable on the Pi

            self._picam = Picamera2()
            # BGR888 matches cv2.imencode's expected channel order, so web.py
            # doesn't need to convert every frame before encoding it.
            video_config = self._picam.create_video_configuration(
                main={"size": self.size, "format": "BGR888"}
            )
            self._picam.configure(video_config)
            self._picam.start()
        else:
            import cv2  # hardware: only importable where opencv is installed

            self._cap = cv2.VideoCapture(self.usb_index)
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.size[0])
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.size[1])
            if not self._cap.isOpened():
                raise RuntimeError("could not open USB camera {}".format(self.usb_index))

    def read_frame(self):
        """Return one frame as a BGR numpy array (what cv2.imencode expects)."""
        if self._picam is not None:
            return self._picam.capture_array()
        ok, frame = self._cap.read()
        if not ok:
            raise RuntimeError("frame read failed")
        return frame

    def stop(self) -> None:
        if self._picam is not None:
            self._picam.stop()
        if self._cap is not None:
            self._cap.release()
