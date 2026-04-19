/**
 * Convert any image File to a Rekognition-compatible JPEG.
 *
 * AWS Rekognition (used by the moderation pipeline) only accepts PNG and JPEG.
 * Chrome's "Save image as…" and many iPhone/Android sources produce WebP / HEIC,
 * which would otherwise be silently skipped by moderation. Normalizing here
 * guarantees every upload is scannable.
 *
 * PNG files pass through unchanged; JPEG files pass through unchanged.
 * Everything else is re-encoded to JPEG at 0.92 quality via <canvas>.
 */
export async function normalizeImageFile(file: File): Promise<File> {
  const isJpeg = file.type === "image/jpeg" || file.type === "image/jpg";
  const isPng = file.type === "image/png";
  if (isJpeg || isPng) return file;

  const dataUrl = await readAsDataUrl(file);
  const img = await loadImage(dataUrl);

  const canvas = document.createElement("canvas");
  canvas.width = img.naturalWidth;
  canvas.height = img.naturalHeight;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("Canvas 2D context unavailable");
  ctx.drawImage(img, 0, 0);

  const blob = await new Promise<Blob | null>((resolve) =>
    canvas.toBlob(resolve, "image/jpeg", 0.92),
  );
  if (!blob) throw new Error("Failed to encode image as JPEG");

  const newName = file.name.replace(/\.[^.]+$/, "") + ".jpg";
  return new File([blob], newName, { type: "image/jpeg" });
}

function readAsDataUrl(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error ?? new Error("FileReader failed"));
    reader.readAsDataURL(file);
  });
}

function loadImage(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("Image decode failed"));
    img.src = src;
  });
}
