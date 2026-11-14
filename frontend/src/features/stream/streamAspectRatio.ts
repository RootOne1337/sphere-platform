export interface StreamFrameDimensions {
  width: number;
  height: number;
}

/** Use the decoded frame shape; 16:9 is the safe pre-frame default for emulator streams. */
export function getStreamAspectRatio(dimensions?: StreamFrameDimensions): string {
  if (
    !dimensions
    || !Number.isFinite(dimensions.width)
    || !Number.isFinite(dimensions.height)
    || dimensions.width <= 0
    || dimensions.height <= 0
  ) {
    return '16 / 9';
  }

  return `${dimensions.width} / ${dimensions.height}`;
}
