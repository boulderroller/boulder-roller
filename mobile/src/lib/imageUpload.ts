import * as FileSystem from 'expo-file-system';
import * as ImageManipulator from 'expo-image-manipulator';
import type * as ImagePicker from 'expo-image-picker';

export interface PreparedNativeImageUpload {
  uri: string;
  name: string;
  mimeType: 'image/jpeg';
  size: number;
  width?: number;
  height?: number;
}

interface PrepareNativeImageOptions {
  fileNamePrefix: string;
  maxDimension?: number;
  compress?: number;
  maxBytes?: number;
}

const DEFAULT_MAX_DIMENSION = 2048;
const DEFAULT_COMPRESS = 0.82;
const DEFAULT_MAX_BYTES = 4 * 1024 * 1024;

function safeBaseName(value: string): string {
  return value
    .toLowerCase()
    .replace(/\.[^.]+$/, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 80) || 'image';
}

async function fileSize(uri: string): Promise<number> {
  const info = await FileSystem.getInfoAsync(uri, { size: true });
  if (info.exists && typeof info.size === 'number') {
    return info.size;
  }
  return 0;
}

export async function prepareNativeImageUpload(
  asset: ImagePicker.ImagePickerAsset,
  options: PrepareNativeImageOptions,
): Promise<PreparedNativeImageUpload> {
  const width = asset.width ?? 0;
  const height = asset.height ?? 0;
  const maxDimension = options.maxDimension ?? DEFAULT_MAX_DIMENSION;
  const largestSide = Math.max(width, height);
  const actions: ImageManipulator.Action[] = [];

  if (largestSide > maxDimension) {
    if (width >= height) {
      actions.push({ resize: { width: maxDimension } });
    } else {
      actions.push({ resize: { height: maxDimension } });
    }
  }

  let manipulated = await ImageManipulator.manipulateAsync(
    asset.uri,
    actions,
    {
      compress: options.compress ?? DEFAULT_COMPRESS,
      format: ImageManipulator.SaveFormat.JPEG,
    },
  );
  let size = await fileSize(manipulated.uri);
  const maxBytes = options.maxBytes ?? DEFAULT_MAX_BYTES;

  if (size > maxBytes) {
    manipulated = await ImageManipulator.manipulateAsync(
      manipulated.uri,
      [],
      {
        compress: 0.68,
        format: ImageManipulator.SaveFormat.JPEG,
      },
    );
    size = await fileSize(manipulated.uri);
  }

  if (size > maxBytes) {
    throw new Error('That image is still too large after processing.');
  }

  return {
    uri: manipulated.uri,
    name: `${safeBaseName(options.fileNamePrefix)}-${Date.now()}.jpg`,
    mimeType: 'image/jpeg',
    size,
    width: manipulated.width,
    height: manipulated.height,
  };
}
