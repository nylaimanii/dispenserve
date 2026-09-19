// dispenserve dispenser
//
// Power: 9V battery into the barrel jack, servo on the 5V pin.
// The servo is only attached (powered with a signal) during a sweep, so it doesn't
// draw holding current or jitter while idle.
//
// Serial, 9600 baud:
//   boot      -> "ready"
//   'd'       -> sweep 0 -> 180, pause, shake to knock the item loose, sweep back to 0,
//                green LED blinks 3 times, then "ok"
//   'x'       -> red LED on for 3s (already served), no reply
//   sensor    -> "near" when something is within 80cm for 0.5s,
//                "away" when nothing is within 80cm for 3s
//                "nosensor" once at boot if the sensor never echoes (not wired?),
//                so the laptop knows to stay awake instead of sleeping forever
//
// A watchdog resets the board if it ever freezes (e.g. a brownout from a sagging
// battery that doesn't trigger a clean reset). After a reset it prints "ready" again.

#include <Servo.h>
#include <avr/wdt.h>

const int SERVO_PIN = 9;
// full pulse range, so 0 and 180 really are the servo's ends
const int SERVO_MIN_US = 500;
const int SERVO_MAX_US = 2500;
const int TRIG_PIN = 3;
const int ECHO_PIN = 4;
const int GREEN_LED = 6;
const int RED_LED = 7;

const int STEP_DELAY_MS = 10;  // 1 degree per 10ms
const int DETACH_PAUSE_MS = 300;
const int HOLD_AT_TOP_MS = 600;
const int SHAKES = 3;        // at the top: 180 -> 165 -> 180, to drop an item that's caught
const int SHAKE_DEGREES = 15;
const int SHAKE_STEP_MS = 3;  // faster than the sweep, so it's a shake and not a sweep
const int SHAKE_PAUSE_MS = 40;
const int GREEN_BLINKS = 3;
const int BLINK_MS = 150;
const unsigned long RED_ON_MS = 3000;

const int NEAR_CM = 80;
const unsigned long NEAR_HOLD_MS = 500;
const unsigned long AWAY_HOLD_MS = 3000;
const unsigned long SENSOR_INTERVAL_MS = 60;  // HC-SR04 needs ~60ms between pings
const unsigned long ECHO_TIMEOUT_US = 6000;   // ~100cm round trip; no echo = nothing near
const unsigned long SELFTEST_TIMEOUT_US = 25000;  // ~4m: a working sensor almost always sees a wall

Servo disc;

bool someoneNear = false;
unsigned long nearSince = 0;  // 0 = not currently seeing something near
unsigned long farSince = 0;   // 0 = not currently seeing nothing
unsigned long lastPing = 0;
unsigned long redOffAt = 0;

// Moves one degree at a time. While blinking, toggles the green LED so the
// blink happens during the sweep instead of adding time before "ok".
void sweep(int from, int to, bool blinkGreen) {
  int step = (to > from) ? 1 : -1;
  unsigned long start = millis();
  for (int pos = from; pos != to + step; pos += step) {
    disc.write(pos);
    wdt_reset();
    if (blinkGreen) {
      unsigned long t = millis() - start;
      bool on = t < (unsigned long)GREEN_BLINKS * 2 * BLINK_MS && (t / BLINK_MS) % 2 == 0;
      digitalWrite(GREEN_LED, on ? HIGH : LOW);
    }
    delay(STEP_DELAY_MS);
  }
  digitalWrite(GREEN_LED, LOW);
}

// Quick back-and-forth at the top so an item resting on the edge of the slot falls through.
void shake() {
  for (int i = 0; i < SHAKES; i++) {
    for (int pos = 180; pos >= 180 - SHAKE_DEGREES; pos--) {
      disc.write(pos);
      delay(SHAKE_STEP_MS);
    }
    delay(SHAKE_PAUSE_MS);
    for (int pos = 180 - SHAKE_DEGREES; pos <= 180; pos++) {
      disc.write(pos);
      delay(SHAKE_STEP_MS);
    }
    delay(SHAKE_PAUSE_MS);
    wdt_reset();
  }
}

void dispense() {
  delay(400);
  disc.write(0);
  disc.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
  sweep(0, 180, true);
  wdt_reset();
  delay(HOLD_AT_TOP_MS);
  shake();
  sweep(180, 0, false);
  disc.detach();
  delay(DETACH_PAUSE_MS);
  Serial.println("ok");

  // the sensor wasn't read during the sweep, so start its timers fresh
  nearSince = 0;
  farSince = 0;
}

long readDistanceCm(unsigned long timeoutUs) {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  unsigned long echo = pulseIn(ECHO_PIN, HIGH, timeoutUs);
  if (echo == 0) return -1;  // nothing within range
  return echo / 58;
}

void updateSensor(unsigned long now) {
  if (now - lastPing < SENSOR_INTERVAL_MS) return;
  lastPing = now;

  long cm = readDistanceCm(ECHO_TIMEOUT_US);
  bool near = cm > 0 && cm <= NEAR_CM;

  if (near) {
    farSince = 0;
    if (nearSince == 0) nearSince = now;
    if (!someoneNear && now - nearSince >= NEAR_HOLD_MS) {
      someoneNear = true;
      Serial.println("near");
    }
  } else {
    nearSince = 0;
    if (farSince == 0) farSince = now;
    if (someoneNear && now - farSince >= AWAY_HOLD_MS) {
      someoneNear = false;
      Serial.println("away");
    }
  }
}

void setup() {
  wdt_disable();
  Serial.begin(9600);
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(GREEN_LED, OUTPUT);
  pinMode(RED_LED, OUTPUT);
  digitalWrite(TRIG_PIN, LOW);

  // home the disc to 0 degrees, then let go
  disc.write(0);
  disc.attach(SERVO_PIN, SERVO_MIN_US, SERVO_MAX_US);
  delay(400);
  disc.detach();

  Serial.println("ready");

  bool echoed = false;
  for (int i = 0; i < 5 && !echoed; i++) {
    echoed = readDistanceCm(SELFTEST_TIMEOUT_US) > 0;
    delay(60);
  }
  if (!echoed) Serial.println("nosensor");

  wdt_enable(WDTO_2S);
}

void loop() {
  wdt_reset();
  if (Serial.available() > 0) {
    char c = Serial.read();
    if (c == 'd') {
      dispense();
    } else if (c == 'x') {
      digitalWrite(RED_LED, HIGH);
      redOffAt = millis() + RED_ON_MS;
    }
  }

  unsigned long now = millis();
  if (redOffAt != 0 && (long)(now - redOffAt) >= 0) {
    digitalWrite(RED_LED, LOW);
    redOffAt = 0;
  }
  updateSensor(now);
}
