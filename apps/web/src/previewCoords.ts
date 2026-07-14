/**
 * Pure 2D preview contain mapping (Packet 08).
 *
 * Single authority for isotropic object-fit:contain scale + letterbox offsets.
 * No DOM. Reused by pointer conversion and circle/polygon/ROI/tracked/debug overlays.
 */

export type ContainLayout = {
  /** Isotropic scale: CSS px per source pixel. */
  scale: number;
  /** Letterbox offset of painted content inside content box (CSS px). */
  xOffset: number;
  yOffset: number;
  wRendered: number;
  hRendered: number;
};

export type ImageBoxMetrics = {
  wBox: number;
  hBox: number;
  wSrc: number;
  hSrc: number;
  borderLeft: number;
  borderTop: number;
  paddingLeft: number;
  paddingTop: number;
};

function clampNum(value: number, min: number, max: number): number {
  if (value < min) return min;
  if (value > max) return max;
  return value;
}

/**
 * CSS object-fit: contain layout for a content box and source image size.
 * Never applies independent X/Y scales. Zero/invalid sizes → scale 0.
 */
export function containLayout(
  wBox: number,
  hBox: number,
  wSrc: number,
  hSrc: number
): ContainLayout {
  if (!(wBox > 0) || !(hBox > 0) || !(wSrc > 0) || !(hSrc > 0)) {
    return { scale: 0, xOffset: 0, yOffset: 0, wRendered: 0, hRendered: 0 };
  }
  const scale = Math.min(wBox / wSrc, hBox / hSrc);
  const wRendered = wSrc * scale;
  const hRendered = hSrc * scale;
  return {
    scale,
    xOffset: (wBox - wRendered) / 2,
    yOffset: (hBox - hRendered) / 2,
    wRendered,
    hRendered
  };
}

/** Content-box local → source image pixel (rounded + clamped like the live UI). */
export function contentToImagePoint(
  xContent: number,
  yContent: number,
  layout: ContainLayout,
  wSrc: number,
  hSrc: number
): { x: number; y: number } {
  if (layout.scale <= 0 || !(wSrc > 0) || !(hSrc > 0)) {
    return { x: 0, y: 0 };
  }
  const xImg = Math.round((xContent - layout.xOffset) / layout.scale);
  const yImg = Math.round((yContent - layout.yOffset) / layout.scale);
  return {
    x: clampNum(xImg, 0, wSrc - 1),
    y: clampNum(yImg, 0, hSrc - 1)
  };
}

/** Source image pixel → content-box local CSS px (then add border/padding for element space). */
export function imageToContentPoint(
  imgX: number,
  imgY: number,
  layout: ContainLayout
): { x: number; y: number } {
  if (layout.scale <= 0) {
    return { x: 0, y: 0 };
  }
  return {
    x: imgX * layout.scale + layout.xOffset,
    y: imgY * layout.scale + layout.yOffset
  };
}

/** Viewport client coords → image pixels using box metrics + contain layout. */
export function clientToImagePointPure(
  clientX: number,
  clientY: number,
  rectLeft: number,
  rectTop: number,
  metrics: ImageBoxMetrics
): { x: number; y: number } {
  const layout = containLayout(metrics.wBox, metrics.hBox, metrics.wSrc, metrics.hSrc);
  if (layout.scale <= 0) {
    return { x: 0, y: 0 };
  }
  const xContent = clientX - rectLeft - metrics.borderLeft - metrics.paddingLeft;
  const yContent = clientY - rectTop - metrics.borderTop - metrics.paddingTop;
  return contentToImagePoint(xContent, yContent, layout, metrics.wSrc, metrics.hSrc);
}

/**
 * Image pixels → coordinates relative to the image element's top-left border edge
 * (matches overlay children of `.preview-canvas` when the img is at canvas origin).
 */
export function imageToClientPointPure(
  imgX: number,
  imgY: number,
  metrics: ImageBoxMetrics
): { x: number; y: number } {
  const layout = containLayout(metrics.wBox, metrics.hBox, metrics.wSrc, metrics.hSrc);
  const content = imageToContentPoint(imgX, imgY, layout);
  return {
    x: content.x + metrics.borderLeft + metrics.paddingLeft,
    y: content.y + metrics.borderTop + metrics.paddingTop
  };
}

export function imageDisplayScalePure(wBox: number, hBox: number, wSrc: number, hSrc: number): number {
  return containLayout(wBox, hBox, wSrc, hSrc).scale;
}

/**
 * Layout box matching Packet 08 CSS:
 *   width: 100%; height: auto; max-height: min(70vh, 720px); object-fit: contain
 *
 * The image element fills ``containerWidth`` (upscales when natural size is smaller).
 * Used height is min(width×aspect, maxHeight). When maxHeight clamps, the layout box
 * may be wider than the painted bitmap; letterbox offsets come from containLayout.
 */
export function intrinsicContainBox(
  wSrc: number,
  hSrc: number,
  containerWidth: number,
  maxHeight: number
): {
  wBox: number;
  hBox: number;
  scale: number;
  wPainted: number;
  hPainted: number;
  xOffset: number;
  yOffset: number;
} {
  if (!(wSrc > 0) || !(hSrc > 0) || !(containerWidth > 0) || !(maxHeight > 0)) {
    return {
      wBox: 0,
      hBox: 0,
      scale: 0,
      wPainted: 0,
      hPainted: 0,
      xOffset: 0,
      yOffset: 0
    };
  }
  const wBox = containerWidth;
  const aspectHeight = containerWidth * (hSrc / wSrc);
  const hBox = Math.min(aspectHeight, maxHeight);
  const layout = containLayout(wBox, hBox, wSrc, hSrc);
  return {
    wBox,
    hBox,
    scale: layout.scale,
    wPainted: layout.wRendered,
    hPainted: layout.hRendered,
    xOffset: layout.xOffset,
    yOffset: layout.yOffset
  };
}
