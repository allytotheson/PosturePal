# Validation and tuning

## Establish the measurement before tuning thresholds

Keep a record of firmware revision, axis mapping, sensor positions, vest fit,
baseline values/variation, thresholds, persistence, motor amplitude, battery/supply
voltage and room conditions. Use `valid=1` data. Defaults are tuning values,
and a quiet serial trace is not proof of correct anatomical tracking.

1. **Verify axes and raw behavior.** Mount all three boards rigidly on one plate,
   with marked axes and no motor coupled to them. Follow the setup axis check.
   Every board must report the same sign and change in sagittal angle. Repeat
   with sideways tilt. A swapped/sign-reversed mapping is a software/setup error;
   recalibration must not be used to hide it.
2. **Check timing.** Sample-count increments should be approximately 104/s per
   IMU over at least 60 s, with no faults. Log maximum gaps and read-time skew;
   use an I2C logic analyzer to inspect DRDY/status reads, transactions, NACKs
   and latency. Exercise serial commands and disconnect/reconnect USB. Confirm
   motor checks and diagnostic output do not interrupt acquisition. Do not merely
   increase the gap limit if the bus cannot keep up.
3. **Verify calibration.** Perform five neutral calibrations without moving the
   fixture and compare baselines/peak-to-peak values. Deliberately move one board
   during averaging: the sample window must restart. Continued movement must
   fail calibration after its 60 s averaging deadline. Confirm alerts are disabled
   during settling/calibration and that `calibrate` stops an existing alert.

## Independent fixture angle test

Use three rigid plates with two hinges. Mark board and plate axes, and mount each
IMU repeatably. Use an independent digital inclinometer with specified accuracy
0.2° or better, checked against a level/protractor, as proposed in report section
7.1. Subtract reference plate angles using the same T3−T12 and T12−L5 signs.

- Test each hinge separately from −30° through +30° in 10° steps, then combined
  configurations. After five seconds of settling, record ten seconds per pose.
  Include smaller 2°, 5° and 8° changes to characterize the sensitivity relevant
  to small slouches.
- Apply common sagittal tilts of −20°, 0° and +20° without changing either hinge.
  Regional measurements should remain close to their prior values. Repeat sideways
  tilt and yaw turns; measure rather than assume cancellation in combined 3D poses.
- Run ten forward/return cycles at roughly 10°/s and 30°/s. Use an independently
  leveled camera at >=120 fps tracking plate markers for dynamic reference and
  latency. Do not use a settled static inclinometer as dynamic ground truth.
- Compute bias, RMSE, maximum absolute error and return-to-baseline residual
  separately for raw regional angles and calibrated deviations. Align timestamped
  reference measurements explicitly and record exclusions. Target <5° regional
  RMSE from the report; do not report that target as an achieved specification.

If a rigid fixture fails, investigate axes, signs, sensor scale, clock/polling,
filter outputs and communications before wearer tests. If the fixture passes
but worn behavior fails, attachment and anatomical-plane assumptions become
stronger suspects.

## Alert-state and failure tests

Use `set 15 10 15 10 2000` for the report's controlled threshold trials; repeat
with intended operating settings. Use signed deviations, not physical whole-body
lean alone, to decide whether a trial should alert.

| Trial | Expected behavior |
|---|---|
| Hold neutral or below threshold | No alert; relevant timer reset |
| 10°, 14°, 16° and 25° regional changes held for 1 s and 4 s | Above-threshold 4 s holds alert; brief or below-threshold holds do not |
| Repeat above with 20 s persistence and 19 s/25 s holds | Only continuously above-threshold 25 s holds alert |
| Alternate upper and lower above-threshold holds, each shorter than persistence | No accumulation across regions |
| Both regions deviate together | Either sustained region can activate the one motor |
| After trigger, return into recovery-to-trigger band | Continue buzzing |
| Both regions reach recovery or closer | Motor RTP becomes zero and standby is confirmed |
| Return just one region to recovery | Continue if the other remains outside recovery |
| Pause, recalibrate, or change settings while buzzing | Stop motor and reset regional timers |
| NACK/short read, frozen data-ready, saturation or altered IMU configuration | FAULT, invalid measurements, shutdown attempt, no silent resume |
| Motor disconnected/unresponsive while alerting | FAULT and UNKNOWN; repeat stop attempts; successful software stop cannot be assumed |
| USB disconnect after calibration | Local detection continues; reconnect and inspect `status` |
| Reset/power cycle | Motor-off initialization; unverified mounting gate and new calibration |

Repeat each region/duration trial at least five times. Measure trigger time and
motor current/output independently; register values cannot prove physical onset
or shutdown. Target >=90% intended-alert detection and onset <=1 s after the
configured persistence ends, matching the report. Recovery should occur on the
next valid regional frame plus I2C/actuator delay; measure it rather than infer
it from a printed line. Exercise repeated movements to expose timer-reset and
return-residual problems.

Inject electrical faults on the bench without wearing the motor. Do not short
powered signal lines. Use a test harness/switch, a simulated NACK device, or
controlled fault injection. A stuck bus can block Wire indefinitely; power may
be needed to stop/reset hardware. An independent enable/power cutoff is required
if guaranteed stopping is a requirement.

## Wearer movement and attachment tests

Start with the motor physically disconnected or monitoring paused while
characterizing movements, then repeat with actual haptics and comparable posture.
Use a side/front camera and position/orientation marks on mounts and garment.

1. **Neutral:** sit in the chosen comfortable baseline, breathe and type naturally.
   Record 60–120 s of variation and drift. Repeat after standing and sitting again.
2. **Small slouches:** deliberately round upper back a little, then lower back,
   for shorter/longer than persistence. Check whether adjacent deviations actually
   change. An invisible regional change may reflect common leaning, inaccurate
   mounting or garment motion rather than an insufficient threshold.
3. **Larger bends:** repeat controlled forward bends and return. Observe sign,
   magnitude and recovery residuals for both regions, including opposing bends.
4. **Sideways and turns:** bend left/right, turn while upright, then turn while
   inclined. Lateral changes are logged only. Record sagittal cross-talk and
   unwanted alerts; combined poses can expose the method's limitations.
5. **Whole-body leaning:** keep back shape as unchanged as possible while
   leaning/reclining from the hips. Pure common sagittal inclination should
   approximately cancel; actual spinal-shape change need not cancel.
6. **Return and repetition:** run ten or more cycles per movement. If buzzing
   continues, inspect sagittal residuals and motor confirmation separately.
   Low measured deviations with UNKNOWN motor state suggest communication;
   persistent deviations suggest calibration, sensor estimate or mounting changes.
7. **Motor interference:** compare motor-off/on traces on a stationary fixture
   and during matched movements. Look for induced tilt, false rest detection,
   supply droop or I2C errors. Relocate/isolate motor and add strain relief if
   needed. Do not simply widen recovery limits to conceal vibration artifacts.
8. **Attachment isolation:** mark sensor orientation and pocket position before
   and after trials. Deliberately loosen one mount, repeat the same sequence,
   then refasten it. Compare with directly attached rigid references. A vest
   moving relative to the wearer cannot be distinguished reliably from body
   motion using these IMUs alone. Recalibrate only after restoring a secure fit.

The report proposes mount rotation <=2° and shift <=5 mm; measure whether the
actual garment achieves those targets. Include cable tension and different
body sizes. Test talking, reaching, reclining, standing/walking and stretching
as ordinary activities, documenting duration and settings. Its >=95% no-unwanted-
alert target is a validation goal. The report's pulse-perceptibility protocol
must be revised for this continuous-buzz implementation; do not claim its 98%
pulse-perception target has been validated here.

## Choose thresholds from recorded data

For each region, compare neutral noise/drift, comfortable ordinary movements and
deliberate sustained changes. Choose a trigger above the observed neutral band
and a recovery lower than trigger but above repeatable return noise. The gap
must be large enough to avoid chatter yet allow comfortable recovery. Choose
persistence to reject short activities; test the same region continuously rather
than the maximum changing region. Adjust one setting at a time and repeat trials
across users/fits. Keep 7.5°/4°/2 s only as a starting point.

If deliberate small slouches are indistinguishable from noise/attachment movement,
do not advertise small-angle sensitivity by lowering thresholds. Improve mounting
and measurement first. If useful operating thresholds cannot separate intended
and ordinary motions, document that limitation or revisit the sensing model.

All unperformed procedures above are proposed tests. See [actual verification](VERIFICATION.md)
for the software tests and compilation completed in this environment.
