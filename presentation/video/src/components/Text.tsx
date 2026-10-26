import React from 'react';
import {useCurrentFrame} from 'remotion';
import {rise} from '../anim';
import {C, F} from '../theme';

export const Kicker: React.FC<{children: React.ReactNode; at?: number; color?: string; style?: React.CSSProperties}> = ({children, at = 0, color = C.amber, style}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{fontFamily: F.mono, fontSize: 24, letterSpacing: 4, textTransform: 'uppercase', color, fontWeight: 500, ...rise(frame, at, 14), ...style}}>
      {children}
    </div>
  );
};

export const Headline: React.FC<{children: React.ReactNode; at?: number; size?: number; style?: React.CSSProperties}> = ({children, at = 0, size = 92, style}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{fontFamily: F.sans, fontSize: size, fontWeight: 600, letterSpacing: -size * 0.03, lineHeight: 1.04, color: C.white, ...rise(frame, at), ...style}}>
      {children}
    </div>
  );
};

export const Serif: React.FC<{children: React.ReactNode; color?: string}> = ({children, color = C.white}) => (
  <span style={{fontFamily: F.serif, fontStyle: 'italic', fontWeight: 400, letterSpacing: 0, color}}>{children}</span>
);

export const Body: React.FC<{children: React.ReactNode; at?: number; size?: number; color?: string; style?: React.CSSProperties}> = ({children, at = 0, size = 36, color = C.white, style}) => {
  const frame = useCurrentFrame();
  return (
    <div style={{fontFamily: F.sans, fontSize: size, lineHeight: 1.35, color, fontWeight: 400, ...rise(frame, at, 18), ...style}}>
      {children}
    </div>
  );
};

export const Tag: React.FC<{children: React.ReactNode; color?: string; solid?: boolean; style?: React.CSSProperties}> = ({children, color = C.amber, solid, style}) => (
  <span
    style={{
      display: 'inline-block',
      fontFamily: F.mono,
      fontSize: 20,
      letterSpacing: 2,
      textTransform: 'uppercase',
      padding: '6px 12px',
      borderRadius: 4,
      border: `1.5px solid ${color}`,
      color: solid ? C.ink : color,
      background: solid ? color : 'rgba(11,11,12,0.72)',
      fontWeight: 500,
      whiteSpace: 'nowrap',
      ...style,
    }}
  >
    {children}
  </span>
);

export const SyntheticTag: React.FC<{style?: React.CSSProperties}> = ({style}) => (
  <Tag solid style={style}>Synthetic demo</Tag>
);
