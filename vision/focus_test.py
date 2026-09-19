"""Live focus check for the external webcam: shows a sharpness score and a face-sized guide oval. q quits."""

import sys

import cv2

# the external usb webcam is usually index 1; fall back to 0 if it's the only camera
CAMERA_INDEXES = [1, 0]


def open_camera():
    for index in CAMERA_INDEXES:
        cap = cv2.VideoCapture(index)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                return index, cap
        cap.release()
    return None, None


def sharpness(frame):
    # variance of the laplacian on the center third of the frame
    h, w = frame.shape[:2]
    center = frame[h // 3 : 2 * h // 3, w // 3 : 2 * w // 3]
    gray = cv2.cvtColor(center, cv2.COLOR_BGR2GRAY)
    return cv2.Laplacian(gray, cv2.CV_64F).var()


def main():
    index, cap = open_camera()
    if cap is None:
        sys.exit(f"no camera found at indexes {CAMERA_INDEXES}")
    print(f"using camera index {index}")

    while True:
        ok, frame = cap.read()
        if not ok:
            print("lost camera feed")
            break

        h, w = frame.shape[:2]
        score = sharpness(frame)

        # face-sized guide oval, taller than wide
        cv2.ellipse(frame, (w // 2, h // 2), (int(h * 0.2), int(h * 0.28)), 0, 0, 360, (0, 255, 0), 2)
        cv2.putText(frame, f"sharpness: {score:.0f}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
        cv2.putText(frame, f"camera {index}  |  q to quit", (20, h - 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        cv2.imshow("dispenserve focus test", frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
