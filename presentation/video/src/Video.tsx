import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, staticFile} from 'remotion';
import {Chrome} from './components/Chrome';
import {media} from './data';
import {ensureFonts} from './fonts';
import {S1Hook} from './scenes/S1Hook';
import {S2Purpose} from './scenes/S2Purpose';
import {S3App} from './scenes/S3App';
import {S4Review} from './scenes/S4Review';
import {S5StreetLab} from './scenes/S5StreetLab';
import {S6Build} from './scenes/S6Build';
import {S7Close} from './scenes/S7Close';
import timeline from './timeline.json';
import {C} from './theme';

ensureFonts();

export type VideoProps = {music: boolean; musicVolume: number};

const SCENES: Record<string, React.FC<{withMusic: boolean}>> = {
  hook: S1Hook,
  purpose: S2Purpose,
  app: S3App,
  review: S4Review,
  streetlab: S5StreetLab,
  build: S6Build,
  close: S7Close,
};

export const NearMissVideo: React.FC<VideoProps> = ({music, musicVolume}) => {
  const withMusic = music && Boolean(media.music);
  const total = timeline.durationInFrames;
  return (
    <AbsoluteFill style={{background: C.ink}}>
      {timeline.scenes.map((s) => {
        const Scene = SCENES[s.id];
        return (
          <Sequence key={s.id} from={s.from} durationInFrames={s.to - s.from} name={s.label}>
            <Scene withMusic={withMusic} />
          </Sequence>
        );
      })}
      <Chrome />
      {withMusic && media.music && (
        <Audio
          src={staticFile(media.music.file)}
          // First 165 s of the track with a 1.5 s fade-in and 4 s fade-out.
          volume={(f) => interpolate(f, [0, 45, total - 120, total - 1], [0, musicVolume, musicVolume, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})}
        />
      )}
    </AbsoluteFill>
  );
};
