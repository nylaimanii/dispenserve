#include <Servo.h>

const int SERVO_PIN = 9;
const int STEP_DELAY_MS = 6;  // 1 degree per 6ms

Servo disc;

void sweep(int from, int to) {
  int step = (to > from) ? 1 : -1;
  for (int pos = from; pos != to + step; pos += step) {
    disc.write(pos);
    delay(STEP_DELAY_MS);
  }
}

void setup() {
  Serial.begin(9600);
  disc.attach(SERVO_PIN);
  disc.write(0);
  Serial.println("ready");
}

void loop() {
  if (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'd') {
      delay(400);
      sweep(0, 180);
      delay(500);
      sweep(180, 0);
      Serial.println("ok");
    }
  }
}
