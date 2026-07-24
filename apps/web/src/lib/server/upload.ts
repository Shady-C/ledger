import { uploadLimits } from './env.js';

const allowedExtensions = new Set(['csv', 'xlsx', 'pdf']);

export type CheckedUpload = {
  name: string;
  body: Uint8Array;
};

function extension(name: string) {
  return name.toLowerCase().split('.').pop() ?? '';
}

function beginsWith(bytes: Uint8Array, expected: number[]) {
  return expected.every((byte, index) => bytes[index] === byte);
}

function validSignature(ext: string, bytes: Uint8Array) {
  if (ext === 'xlsx') return beginsWith(bytes, [0x50, 0x4b]);
  if (ext === 'pdf') return beginsWith(bytes, [0x25, 0x50, 0x44, 0x46, 0x2d]);
  if (ext === 'csv') return !bytes.subarray(0, Math.min(bytes.length, 8192)).includes(0);
  return false;
}

export async function checkUploads(values: FormDataEntryValue[]): Promise<
  | { ok: true; files: CheckedUpload[] }
  | { ok: false; message: string }
> {
  const limits = uploadLimits();
  const incoming = values.filter((value): value is File => value instanceof File && value.size > 0);
  if (incoming.length === 0) return { ok: false, message: 'Choose at least one statement file.' };
  if (incoming.length > limits.maxFiles) {
    return { ok: false, message: `Upload no more than ${limits.maxFiles} files at once.` };
  }
  if (incoming.some((file) => file.size > limits.maxFileBytes)) {
    return { ok: false, message: 'One or more files exceed the upload size limit.' };
  }
  if (incoming.reduce((sum, file) => sum + file.size, 0) > limits.maxTotalBytes) {
    return { ok: false, message: 'The combined upload exceeds the upload size limit.' };
  }

  const files: CheckedUpload[] = [];
  for (const file of incoming) {
    const ext = extension(file.name);
    if (!allowedExtensions.has(ext)) {
      return { ok: false, message: 'Only CSV, XLSX, and PDF statements are supported.' };
    }
    const body = new Uint8Array(await file.arrayBuffer());
    if (!validSignature(ext, body)) {
      return { ok: false, message: `${file.name} does not appear to be a valid ${ext.toUpperCase()} file.` };
    }
    files.push({ name: file.name, body });
  }
  return { ok: true, files };
}
