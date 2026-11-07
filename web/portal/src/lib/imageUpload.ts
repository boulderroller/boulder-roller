const DEFAULT_MAX_DIMENSION = 2048;
const DEFAULT_QUALITY = 0.82;
const DEFAULT_MAX_BYTES = 4 * 1024 * 1024;

export type BrowserImageUploadOptions = {
  fileNamePrefix: string;
  maxDimension?: number;
  quality?: number;
  maxBytes?: number;
};

function safeBaseName(fileName: string, fallback: string): string {
  const base = fileName.replace(/\.[^.]+$/, '').trim() || fallback;
  return base
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || fallback;
}

function canvasToBlob(
  canvas: HTMLCanvasElement,
  mimeType: string,
  quality: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob((blob) => {
      if (!blob) {
        reject(new Error('Could not process image for upload'));
        return;
      }
      resolve(blob);
    }, mimeType, quality);
  });
}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file);
    const image = new Image();
    image.onload = () => {
      URL.revokeObjectURL(objectUrl);
      resolve(image);
    };
    image.onerror = () => {
      URL.revokeObjectURL(objectUrl);
      reject(new Error('Could not read that image. Try a JPEG, PNG, or WebP file.'));
    };
    image.src = objectUrl;
  });
}

export async function prepareBrowserImageUpload(
  file: File,
  options: BrowserImageUploadOptions,
): Promise<File> {
  if (!file.type.startsWith('image/')) {
    throw new Error('Choose an image file.');
  }

  const maxDimension = options.maxDimension ?? DEFAULT_MAX_DIMENSION;
  const quality = options.quality ?? DEFAULT_QUALITY;
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;
  const image = await loadImage(file);
  const scale = Math.min(1, maxDimension / Math.max(image.naturalWidth, image.naturalHeight));
  const width = Math.max(1, Math.round(image.naturalWidth * scale));
  const height = Math.max(1, Math.round(image.naturalHeight * scale));

  const canvas = document.createElement('canvas');
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext('2d');
  if (!ctx) {
    throw new Error('Could not process image for upload');
  }
  ctx.drawImage(image, 0, 0, width, height);

  let blob = await canvasToBlob(canvas, 'image/jpeg', quality);
  if (blob.size > maxBytes && quality > 0.65) {
    blob = await canvasToBlob(canvas, 'image/jpeg', 0.68);
  }
  if (blob.size > maxBytes) {
    throw new Error('That image is still too large after processing.');
  }

  const name = `${safeBaseName(file.name, options.fileNamePrefix)}.jpg`;
  return new File([blob], name, {
    type: 'image/jpeg',
    lastModified: Date.now(),
  });
}
