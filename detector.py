import cv2
import numpy as np
from ultralytics import YOLO

HAAR_CASCADE_PATH = "haarcascade_plate.xml"

class DetectionEngine:
    """
    Handles Offline YOLO Vehicle Tracking + Haar Cascade & Contour Plate Localization.
    """
    def __init__(self):
        print("[DETECTOR] â³ Loading YOLOv8n (Offline Mode)...")
        self.vehicle_model = YOLO('yolov8n.pt') 
        self.plate_cascade = cv2.CascadeClassifier(HAAR_CASCADE_PATH)

    def track_vehicles(self, frame):
        """
        Returns tracked vehicles: [(x1,y1,x2,y2, track_id, vehicle_class_name), ...]
        Only looks for car, motorcycle, bus, train, truck.
        """
        results = self.vehicle_model.track(frame, persist=True, verbose=False, conf=0.3, classes=[1, 2, 3, 5, 6, 7])
        vehicles = []

        for r in results:
            if not r.boxes or r.boxes.id is None: continue
            
            for box, track_id in zip(r.boxes, r.boxes.id):
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                vcls = int(box.cls[0])
                v_name = self.vehicle_model.names[vcls].upper()
                tid = int(track_id)
                
                area = (x2-x1) * (y2-y1)
                if area < 1000: continue # Ignore far vehicles
                
                vehicles.append((x1, y1, x2, y2, tid, v_name))
                
        return vehicles

    def find_plates(self, vehicle_img):
        """
        Extracts plausible plates from a vehicle crop using Haar + Contours.
        """
        if vehicle_img is None or vehicle_img.size == 0: return []
        
        plates_found = []
        gray = cv2.cvtColor(vehicle_img, cv2.COLOR_BGR2GRAY)
        
        # 1. Haar Cascade (Fastest)
        plates_haar = self.plate_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=4, minSize=(20, 10))
        for (x, y, w, h) in plates_haar:
            aspect_ratio = float(w) / h
            if 1.5 <= aspect_ratio <= 5.5:
                pad_w, pad_h = int(w * 0.1), int(h * 0.15)
                x1, y1 = max(0, x - pad_w), max(0, y - pad_h)
                x2, y2 = min(vehicle_img.shape[1], x + w + pad_w), min(vehicle_img.shape[0], y + h + pad_h)
                
                plate_crop = vehicle_img[y1:y2, x1:x2]
                if plate_crop.size > 0:
                    plates_found.append(plate_crop)

        if plates_found: return plates_found

        # 2. Contour Search Fallback for difficult angles
        rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (13, 5))
        blackhat = cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, rect_kernel)
        
        grad_x = cv2.Sobel(blackhat, ddepth=cv2.CV_32F, dx=1, dy=0, ksize=-1)
        grad_x = np.absolute(grad_x)
        min_v, max_v = np.min(grad_x), np.max(grad_x)
        if max_v - min_v > 0:
            grad_x = (255 * ((grad_x - min_v) / (max_v - min_v))).astype("uint8")
        
        grad_x = cv2.GaussianBlur(grad_x, (5, 5), 0)
        grad_x = cv2.morphologyEx(grad_x, cv2.MORPH_CLOSE, rect_kernel)
        thresh = cv2.threshold(grad_x, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)[1]
        
        cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        cnts = sorted(cnts, key=cv2.contourArea, reverse=True)[:10]

        for c in cnts:
            x, y, w, h = cv2.boundingRect(c)
            ar = w / float(h) if h > 0 else 0
            if 1.5 <= ar <= 5.5 and w > 40 and h > 15:
                plate_crop = vehicle_img[y:y+h, x:x+w]
                plates_found.append(plate_crop)

        return plates_found

