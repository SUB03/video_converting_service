// Proxied to the FastAPI service by Nitro (see vite.config.ts)
export const API_BASE = "/api";

// Must match VideoFormat in video_converter_service/models.py
export const VIDEO_FORMATS = [
	"mp4",
	"webm",
	"mkv",
	"mov",
	"avi",
	"gif",
] as const;
export type VideoFormat = (typeof VIDEO_FORMATS)[number];

export type UploadResponse = { job_id: string };

export function apiUrl(path: string) {
	return `${API_BASE}${path}`;
}

// FastAPI errors: {"detail": "message"} or {"detail": [{"msg": ...}, ...]}
function errorMessage(status: number, body: unknown): string {
	const detail = (body as { detail?: unknown } | null)?.detail;
	if (typeof detail === "string") return detail;
	if (Array.isArray(detail)) {
		return detail.map((d: { msg?: string }) => d.msg ?? String(d)).join("; ");
	}
	return `Upload failed: HTTP ${status}`;
}

// XHR instead of fetch: fetch can't report upload progress
export function uploadVideo(
	file: File,
	targetFormats: VideoFormat[],
	onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		const body = new FormData();
		body.append("file", file);
		for (const format of targetFormats) body.append("target_formats", format);

		xhr.open("POST", apiUrl("/videos"));
		xhr.responseType = "json";
		xhr.upload.onprogress = (e) => {
			if (e.lengthComputable) onProgress?.((e.loaded / e.total) * 100);
		};
		xhr.onload = () => {
			const res = xhr.response as UploadResponse | null;
			if (xhr.status < 200 || xhr.status >= 300) {
				reject(new Error(errorMessage(xhr.status, xhr.response)));
			} else if (!res?.job_id) {
				reject(new Error(`No job_id in response: ${JSON.stringify(res)}`));
			} else {
				resolve(res);
			}
		};
		xhr.onerror = () => reject(new Error("Network error"));
		xhr.send(body);
	});
}

export function jobEventsUrl(jobId: string) {
	return apiUrl(`/videos/${encodeURIComponent(jobId)}/events`);
}
