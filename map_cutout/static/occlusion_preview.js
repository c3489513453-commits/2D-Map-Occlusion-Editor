function pointOnSegment(point, start, end) {
  const cross = (point.y - start[1]) * (end[0] - start[0])
    - (point.x - start[0]) * (end[1] - start[1]);
  if (Math.abs(cross) > 1e-7) return false;
  return point.x >= Math.min(start[0], end[0]) && point.x <= Math.max(start[0], end[0])
    && point.y >= Math.min(start[1], end[1]) && point.y <= Math.max(start[1], end[1]);
}

export function pointInPolygon(point, polygon) {
  if (!polygon || polygon.length < 3) return false;
  let inside = false;
  for (let index = 0, previous = polygon.length - 1; index < polygon.length; previous = index++) {
    const start = polygon[previous];
    const end = polygon[index];
    if (pointOnSegment(point, start, end)) return true;
    const crosses = (end[1] > point.y) !== (start[1] > point.y)
      && point.x < (start[0] - end[0]) * (point.y - end[1]) / (start[1] - end[1]) + end[0];
    if (crosses) inside = !inside;
  }
  return inside;
}

export function opaqueFootpoint(pixels, width, height) {
  for (let y = height - 1; y >= 0; y -= 1) {
    let first = -1;
    let last = -1;
    for (let x = 0; x < width; x += 1) {
      if (pixels[(y * width + x) * 4 + 3] > 0) {
        if (first < 0) first = x;
        last = x;
      }
    }
    if (first >= 0) return {x: (first + last) / 2, y, left: first, right: last};
  }
  throw new Error("人物图片完全透明，请选择包含人物的 PNG");
}

function pointSegmentDistance(point, start, end) {
  const dx = end[0] - start[0];
  const dy = end[1] - start[1];
  const lengthSquared = dx * dx + dy * dy;
  if (!lengthSquared) return Math.hypot(point.x - start[0], point.y - start[1]);
  const amount = Math.max(0, Math.min(1,
    ((point.x - start[0]) * dx + (point.y - start[1]) * dy) / lengthSquared));
  return Math.hypot(point.x - (start[0] + amount * dx), point.y - (start[1] + amount * dy));
}

export function lineYAtX(line, x) {
  if (!line || line.length < 2) return null;
  for (let index = 1; index < line.length; index += 1) {
    const start = line[index - 1];
    const end = line[index];
    if (x < Math.min(start[0], end[0]) || x > Math.max(start[0], end[0])) continue;
    if (start[0] === end[0]) return Math.max(start[1], end[1]);
    const amount = (x - start[0]) / (end[0] - start[0]);
    return start[1] + amount * (end[1] - start[1]);
  }
  return null;
}

export function footIsBehindLine(foot, line) {
  const y = lineYAtX(line, foot.x);
  return y !== null && foot.y <= y;
}

export function footprintIsBehindLine(position, footpoint, scale, line) {
  if (!position || !footpoint || !line || line.length < 2) return false;
  const leftPixel = Number.isFinite(footpoint.left) ? footpoint.left : footpoint.x;
  const rightPixel = Number.isFinite(footpoint.right) ? footpoint.right : footpoint.x;
  const left = position.x + (leftPixel - footpoint.x) * scale;
  const right = position.x + (rightPixel - footpoint.x) * scale;
  const footprintLeft = Math.min(left, right);
  const footprintRight = Math.max(left, right);
  for (let index = 1; index < line.length; index += 1) {
    const start = line[index - 1];
    const end = line[index];
    const overlapLeft = Math.max(footprintLeft, Math.min(start[0], end[0]));
    const overlapRight = Math.min(footprintRight, Math.max(start[0], end[0]));
    if (overlapLeft > overlapRight) continue;
    if (start[0] === end[0]) {
      if (position.y <= Math.max(start[1], end[1])) return true;
      continue;
    }
    const yAt = x => start[1] + (x - start[0]) / (end[0] - start[0]) * (end[1] - start[1]);
    if (position.y <= Math.max(yAt(overlapLeft), yAt(overlapRight))) return true;
  }
  return false;
}

export function nearestLineIndex(point, lines, threshold) {
  let nearest = -1;
  let best = threshold;
  for (let lineIndex = 0; lineIndex < (lines || []).length; lineIndex += 1) {
    const line = lines[lineIndex];
    for (let index = 1; index < line.length; index += 1) {
      const distance = pointSegmentDistance(point, line[index - 1], line[index]);
      if (distance <= best) {
        best = distance;
        nearest = lineIndex;
      }
    }
  }
  return nearest;
}

export function nearestLineNode(point, lines, threshold) {
  let nearest = null;
  let best = threshold;
  for (let lineIndex = 0; lineIndex < (lines || []).length; lineIndex += 1) {
    for (let nodeIndex = 0; nodeIndex < lines[lineIndex].length; nodeIndex += 1) {
      const node = lines[lineIndex][nodeIndex];
      const distance = Math.hypot(point.x - node[0], point.y - node[1]);
      if (distance <= best) {
        best = distance;
        nearest = {lineIndex, nodeIndex};
      }
    }
  }
  return nearest;
}
