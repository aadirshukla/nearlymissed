import {Easing, interpolate} from 'remotion';

// All motion is a pure function of the frame number (no CSS transitions).
const clamp = {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'} as const;
export const ease = Easing.bezier(0.22, 1, 0.36, 1);
export const easeInOut = Easing.bezier(0.65, 0, 0.35, 1);

export const ramp = (frame: number, from: number, to: number, a = 0, b = 1, easing = ease) =>
  interpolate(frame, [from, to], [a, b], {...clamp, easing});

// Opacity for an element that fades in at `start` and out at `end`.
export const fadeInOut = (frame: number, start: number, end: number, len = 12) =>
  Math.min(ramp(frame, start, start + len), 1 - ramp(frame, end - len, end, 0, 1, easeInOut));

// Rise-and-fade entrance: returns style fragment.
export const rise = (frame: number, start: number, distance = 28, len = 18) => {
  const k = ramp(frame, start, start + len);
  return {opacity: k, transform: `translateY(${(1 - k) * distance}px)`};
};

export const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
