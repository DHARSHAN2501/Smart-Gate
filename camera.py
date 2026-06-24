import cv2
import threading

class CameraStream:
    """
    Multithreaded camera reader to prevent missing frames and OpenCV freezing.
    """
    def __init__(self, src=0):
        self.stream = None
        self.src = src
        self.started = False
        self.read_lock = threading.Lock()
        
        # Try finding a working camera
        for i in [self.src, 0, 1, 2]:
            cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            if cap.isOpened():
                print(f"[CAM] 🎥 Connected to Camera {i}")
                self.stream = cap
                self.src = i
                break
            cap.release()

        if not self.stream or not self.stream.isOpened():
            print("[CAM] ❌ Camera failed to initialize.")
            self.frame = None
            return

        self.stream.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.stream.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        
        # Read first frame
        (self.grabbed, self.frame) = self.stream.read()
        self.started = False
        
    def start(self):
        if self.started:
            return self

        if self.stream and self.stream.isOpened():
            self.started = True
            # Daemon thread runs in background
            self.thread = threading.Thread(target=self.update, args=())
            self.thread.daemon = True
            self.thread.start()
        return self

    def update(self):
        # Keep looping until thread stops
        while self.started:
            (grabbed, frame) = self.stream.read()
            self.read_lock.acquire()
            self.grabbed, self.frame = grabbed, frame
            self.read_lock.release()

    def read(self):
        self.read_lock.acquire()
        frame = self.frame.copy() if self.frame is not None else None
        grabbed = self.grabbed
        self.read_lock.release()
        return grabbed, frame

    def stop(self):
        self.started = False
        if self.thread.is_alive():
            self.thread.join()
        if self.stream:
            self.stream.release()

    def __del__(self):
        self.stop()
