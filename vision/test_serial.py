"""Manual test for the dispenser: press enter to send 'd' and print the Arduino's reply."""

import glob
import sys
import time

import serial


def find_port():
    ports = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*"))
    return ports[0] if ports else None


def main():
    port = find_port()
    if port is None:
        sys.exit("no arduino found (looked for /dev/cu.usbmodem* and /dev/cu.usbserial*)")

    print(f"opening {port} at 9600")
    # timeout covers a full dispense cycle (sweep, hold, shake, sweep back) with margin
    with serial.Serial(port, 9600, timeout=10) as ser:
        time.sleep(2)  # opening the port resets the uno
        print(ser.readline().decode(errors="replace").strip() or "(no ready line)")

        while True:
            try:
                input("press enter to dispense (ctrl+c to quit) ")
            except (KeyboardInterrupt, EOFError):
                print()
                break
            ser.write(b"d")
            reply = ser.readline().decode(errors="replace").strip()
            print(reply or "(no reply before timeout)")


if __name__ == "__main__":
    main()
