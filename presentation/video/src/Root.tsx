import React from 'react';
import {Composition, Still} from 'remotion';
import {Poster} from './Poster';
import timeline from './timeline.json';
import {NearMissVideo, VideoProps} from './Video';

export const Root: React.FC = () => (
  <>
    <Composition
      id="NearMissDemo"
      component={NearMissVideo}
      durationInFrames={timeline.durationInFrames}
      fps={timeline.fps}
      width={timeline.width}
      height={timeline.height}
      defaultProps={{music: true, musicVolume: 0.5} satisfies VideoProps}
    />
    <Still id="NearMissPoster" component={Poster} width={timeline.width} height={timeline.height} />
  </>
);
