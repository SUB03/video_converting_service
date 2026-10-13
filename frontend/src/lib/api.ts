// Proxied to the FastAPI service by Vite in dev (see vite.config.ts)
export const API_BASE = "/api";

export type UploadResponse = { job_id: string };

// XHR instead of fetch: fetch can't report upload progress
export function uploadVideo(
	file: File,
	onProgress?: (percent: number) => void,
): Promise<UploadResponse> {
	return new Promise((resolve, reject) => {
		const xhr = new XMLHttpRequest();
		const body = new FormData();
		body.append("file", file);

		xhr.open("POST", `${API_BASE}/videos`);
		xhr.responseType = "json";
		xhr.upload.onprogress = (e) => {
			if (e.lengthComputable) onProgress?.((e.loaded / e.total) * 100);
		};
		xhr.onload = () => {
			const res = xhr.response as UploadResponse | null;
			if (xhr.status < 200 || xhr.status >= 300) {
				reject(new Error(`Upload failed: HTTP ${xhr.status}`));
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
	return `${API_BASE}/videos/${encodeURIComponent(jobId)}/events`;
}
