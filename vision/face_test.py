"""Face detection check: boxes one face from the built-in camera and prints its embedding length once a second. q quits."""

import sys
import time

import cv2
from insightface.app import FaceAnalysis

# the built-in facetime camera is usually index 0 (the external usb webcam is usually 1)
CAMERA_INDEX = 0


def main():
    app = FaceAnalysis(
        name="buffalo_l",
        allowed_modules=["detection", "recognition"],
        providers=["CPUExecutionProvider"],
    )
    app.prepare(ctx_id=-1, det_size=(640, 640))

    cap = cv2.VideoCapture(CAMERA_INDEX)
    if not cap.isOpened():
        sys.exit(f"could not open camera {CAMERA_INDEX}")
    print(f"using camera index {CAMERA_INDEX}", flush=True)

    last_print = 0.0
    while True:
        ok, frame = cap.read()
        if not ok:
            print("lost camera feed", flush=True)
            break

        faces = app.get(frame, max_num=1)
        if faces:
            face = faces[0]
            x1, y1, x2, y2 = face.bbox.astype(int)
            cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        now = time.time()
        if now - last_print >= 1.0:
            if faces:
                print(f"embedding length: {len(faces[0].normed_embedding)}", flush=True)
            else:
                print("no face", flush=True)
            last_print = now

        cv2.imshow("dispenserve face test", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
