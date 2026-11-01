import document from './fixtures/recorded-case.json' with { type: 'json' };
import assets from './fixtures/recorded-assets.json' with { type: 'json' };

export const recordedDocument = document;

export function recordedAsset(caseId, slot, step = 3) {
  const record = Object.hasOwn(assets, caseId) ? assets[caseId] : null;
  const asset = record && (slot !== 'video' && record.steps ? record.steps[step]?.[slot] : record[slot]);
  if (!asset || !/^recorded\/[A-Za-z0-9][A-Za-z0-9._-]*\.(png|mp4)$/.test(asset.path)
      || !Number.isInteger(asset.bytes) || asset.bytes < 1 || asset.bytes > 8000000
      || !/^[0-9a-f]{64}$/.test(asset.sha256)) throw Error('Recorded asset is unavailable.');
  return asset;
}

// Only this trusted static catalog can initiate reads. Uploaded JSON never
// supplies a URL/path here. These are same-origin static reads, not Meta calls.
export async function loadRecordedMedia(caseId, slot, step = 3, read = globalThis.fetch) {
  const asset = recordedAsset(caseId, slot, step);
  const base = new URL(import.meta.url);
  const url = new URL(asset.path, base);
  if (url.origin !== base.origin) throw Error('Recorded media origin mismatch.');
  const response = await read(url.href, { credentials: 'omit', redirect: 'error', cache: 'no-store' });
  if (!response.ok || response.redirected) throw Error('Recorded media is not included in this copy.');
  return verifyRecordedBytes(asset, await response.arrayBuffer());
}

export async function verifyRecordedBytes(asset, bytes) {
  if (bytes.byteLength !== asset.bytes || bytes.byteLength > 8000000) throw Error('Recorded media size mismatch.');
  if (!['image/png', 'video/mp4'].includes(asset.type)) throw Error('Recorded media type mismatch.');
  const hash = Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256', bytes)), x => x.toString(16).padStart(2, '0')).join('');
  if (hash !== asset.sha256) throw Error('Recorded media hash mismatch.');
  return { file: new File([bytes], asset.path.split('/').pop(), { type: asset.type }), expectedHash: asset.sha256 };
}
