import easyocr
import re
import cv2
import numpy as np
import torch

class OCREngine:
    def __init__(self):
        # Ensure offline execution by relying only on previously downloaded models
        # Uses GPU if available
        self.use_gpu = torch.cuda.is_available()
        print(f"[OCR] 🚀 Initializing EasyOCR Engine... (GPU: {'ENABLED' if self.use_gpu else 'DISABLED'})")
        self.reader = easyocr.Reader(['en'], gpu=self.use_gpu) 

    def preprocess_plate(self, img):
        """
        Advanced preprocessing tailored for OCR accuracy.
        """
        if img is None or img.size == 0: return None

        # 1. Resize for clarity
        h, w = img.shape[:2]
        target_h = 100
        scale = target_h / h
        img = cv2.resize(img, (int(w * scale), target_h), interpolation=cv2.INTER_CUBIC)
        
        # 2. Grayscale & Contrast
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        contrast = clahe.apply(gray)

        # 3. Denoising & Sharpening
        denoised = cv2.bilateralFilter(contrast, 7, 50, 50)
        sharpen_kernel = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        sharpened = cv2.filter2D(denoised, -1, sharpen_kernel)
        
        # 4. Adaptive Thresholding
        thresh = cv2.adaptiveThreshold(sharpened, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        
        return thresh

    def validate_indian_plate(self, text):
        """
        Validate Indian plate regex exactly for robust detection.
        Returns cleaned string or None.
        """
        if not text: return None
        text = re.sub(r'[^A-Z0-9]', '', text.upper())
        patterns = [
            r"([A-Z]{2}[0-9]{2}[A-Z]{1,2}[0-9]{4})", 
            r"([0-9]{2}BH[0-9]{4}[A-Z]{1,2})",
            r"([A-Z]{2}[0-9]{2}[0-9]{4})",
            r"([A-Z]{2}[0-9]{1,2}[A-Z]{1,3}[0-9]{4})"
        ]
        for p in patterns:
            match = re.search(p, text)
            if match:
                valid = match.group(1)
                if len(valid) >= 6: return valid
        return None

    def read_plate(self, plate_img):
        """
        Reads plate, applies validation, and returns (plate_text, score).
        """
        processed = self.preprocess_plate(plate_img)
        if processed is None: return None, 0

        results = self.reader.readtext(
            processed, 
            detail=1, 
            paragraph=False,
            allowlist='ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789',
            contrast_ths=0.1, 
            adjust_contrast=0.4
        )
        
        if not results: return None, 0
        
        results.sort(key=lambda x: x[0][0][1])
        raw_text = "".join([res[1] for res in results])

        valid_plate = self.validate_indian_plate(raw_text)
        if valid_plate:
            score = len(valid_plate) # Assign a confidence heuristic based on successful chars parsed
            return valid_plate, score

        return None, 0
