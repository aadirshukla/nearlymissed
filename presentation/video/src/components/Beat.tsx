import React from 'react';
import {AbsoluteFill, useCurrentFrame} from 'remotion';
import {fadeInOut} from '../anim';
import {C} from '../theme';
import {Body, Headline, Kicker} from './Text';

// Text column on the left, proof (capture/diagram) on the right.
export const SplitBeat: React.FC<{
  duration: number;
  kicker: string;
  title: React.ReactNode;
  body?: React.ReactNode;
  extra?: React.ReactNode;
  children: React.ReactNode;
  textWidth?: number;
}> = ({duration, kicker, title, body, extra, children, textWidth = 520}) => {
  const frame = useCurrentFrame();
  const o = fadeInOut(frame, 0, duration, 12);
  return (
    <AbsoluteFill style={{opacity: o}}>
      <div style={{position: 'absolute', left: 120, top: 170, width: textWidth}}>
        <Kicker at={2}>{kicker}</Kicker>
        <Headline at={6} size={58} style={{marginTop: 22}}>
          {title}
        </Headline>
        {body && (
          <Body at={14} size={30} color={C.muted} style={{marginTop: 28}}>
            {body}
          </Body>
        )}
        {extra}
      </div>
      <div style={{position: 'absolute', right: 120, top: 150}}>{children}</div>
    </AbsoluteFill>
  );
};
